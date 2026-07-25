"""
Context Compressor — semantic token-budget compression for chat history.

Legacy algorithmic fallback used when the user has set zero manual flags.
Combines TextRank (structural centrality) and BM25 (query relevance) to
select the most important older messages that fit within a token budget.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from utils.logger import logger


class ContextCompressor:
    """
    Compresses chat history into a subset of important messages to fit a token budget.

    Uses TF-IDF, TextRank for structural importance, and BM25 for query relevance.

    Parameters
    ----------
    recent_count : int
        Number of most recent messages to unconditionally include. Default is 10.
    chunk_size : int
        Number of consecutive older messages to group together for analysis. Default is 3.
    alpha : float
        Weight for TextRank centrality (1 - alpha for BM25). Default is 0.4.
    edge_threshold : float
        Cosine similarity threshold for TextRank graph edges. Default is 0.3.
    max_tokens : int
        Maximum number of tokens allowed in the final context. Default is 4000.
    """

    def __init__(
        self,
        recent_count: int = 10,
        chunk_size: int = 3,
        alpha: float = 0.4,
        edge_threshold: float = 0.3,
        max_tokens: int = 4000,
    ) -> None:
        self.recent_count = recent_count
        self.chunk_size = chunk_size
        self.alpha = alpha
        self.edge_threshold = edge_threshold
        self.max_tokens = max_tokens

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Estimate token count as ``len(text.split()) * 1.3``."""
        return int(len(text.split()) * 1.3)

    def _estimate_message_tokens(self, message: dict[str, Any]) -> int:
        """Estimate the token count for a single message dict."""
        return self._estimate_tokens(message.get("content", ""))

    def build_context(
        self, chat_history: list[dict[str, Any]], current_query: str
    ) -> list[dict[str, Any]]:
        """
        Select a subset of messages from *chat_history* that fit the token budget,
        prioritising recent messages, structurally central chunks (TextRank), and
        query-relevant chunks (BM25).

        Returns a chronologically ordered list of message dicts.
        """
        if len(chat_history) <= self.recent_count:
            return chat_history.copy()

        recent_messages = chat_history[-self.recent_count:]
        older_messages = chat_history[:-self.recent_count]

        # Token budget calculation
        recent_tokens = sum(self._estimate_message_tokens(msg) for msg in recent_messages)
        query_tokens = self._estimate_tokens(current_query)
        budget = self.max_tokens - recent_tokens - query_tokens

        if budget <= 0:
            logger.warning("ContextCompressor: Token budget too small. Only returning recent messages.")
            return recent_messages.copy()

        # Step 2 — Chunk older messages
        older_chunks: list[str] = []
        chunk_mappings: list[list[int]] = []  # Maps chunk index to original message indices
        for i in range(0, len(older_messages), self.chunk_size):
            chunk_msgs = older_messages[i:i + self.chunk_size]
            chunk_text = " ".join(msg.get("content", "") for msg in chunk_msgs)
            older_chunks.append(chunk_text)
            chunk_mappings.append(list(range(i, min(i + self.chunk_size, len(older_messages)))))

        recent_text_chunks = [msg.get("content", "") for msg in recent_messages]
        all_chunks = older_chunks + recent_text_chunks

        # Step 3 — Compute TF-IDF vectors
        vectorizer = TfidfVectorizer(max_features=5000)
        try:
            tfidf_matrix = vectorizer.fit_transform(all_chunks)
        except ValueError:
            # e.g., empty vocabulary if all text is stop words or empty
            return recent_messages.copy()

        # Step 4 — TextRank centrality
        sim_matrix = cosine_similarity(tfidf_matrix)

        # Keep edges above threshold and set diagonal to 0
        np.fill_diagonal(sim_matrix, 0)
        sim_matrix[sim_matrix < self.edge_threshold] = 0

        # Convert to stochastic transition matrix
        row_sums = sim_matrix.sum(axis=1)
        row_sums[row_sums == 0] = 1.0
        transition_matrix = sim_matrix / row_sums[:, np.newaxis]

        # PageRank iterative algorithm
        n = transition_matrix.shape[0]
        d = 0.85
        pr = np.ones(n) / n
        for _ in range(30):
            new_pr = (1 - d) / n + d * transition_matrix.T.dot(pr)
            if np.linalg.norm(new_pr - pr) < 1e-6:
                pr = new_pr
                break
            pr = new_pr

        textrank_scores = pr[:len(older_chunks)]

        # Step 5 — BM25 query relevance
        bm25_scores = np.zeros(len(older_chunks))
        if current_query.strip():
            k1 = 1.5
            b = 0.75

            tokenized_chunks = [chunk.split() for chunk in all_chunks]
            tokenized_query = current_query.split()

            doc_lengths = np.array([len(chunk) for chunk in tokenized_chunks])
            avgdl = float(np.mean(doc_lengths)) if len(doc_lengths) > 0 else 1.0
            avgdl = max(avgdl, 1e-6)

            n_docs = len(all_chunks)
            df: dict[str, int] = {}
            for chunk in tokenized_chunks:
                for term in set(chunk):
                    df[term] = df.get(term, 0) + 1

            idf: dict[str, float] = {}
            for term, freq in df.items():
                idf[term] = math.log((n_docs - freq + 0.5) / (freq + 0.5) + 1.0)

            for i, chunk_text in enumerate(older_chunks):
                chunk_tokens = chunk_text.split()
                score = 0.0
                dl = len(chunk_tokens)
                for q_term in tokenized_query:
                    if q_term in idf:
                        tf = chunk_tokens.count(q_term)
                        term_score = idf[q_term] * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / avgdl))
                        score += term_score
                bm25_scores[i] = score

        # Step 6 — Final scoring
        tr_scaled = self._min_max_scale(textrank_scores)

        if current_query.strip():
            bm25_scaled = self._min_max_scale(bm25_scores)
            final_scores = self.alpha * tr_scaled + (1 - self.alpha) * bm25_scaled
        else:
            final_scores = tr_scaled

        # Step 7 — Greedy selection within token budget
        sorted_indices = np.argsort(final_scores)[::-1]
        selected_older_indices: set[int] = set()

        for idx in sorted_indices:
            chunk_msgs = [older_messages[msg_idx] for msg_idx in chunk_mappings[idx]]
            chunk_tokens = sum(self._estimate_message_tokens(msg) for msg in chunk_msgs)

            if chunk_tokens <= budget:
                budget -= chunk_tokens
                selected_older_indices.update(chunk_mappings[idx])
            else:
                # Fallback: if chunk is too large, attempt individual messages
                for msg_idx in chunk_mappings[idx]:
                    msg = older_messages[msg_idx]
                    msg_tokens = self._estimate_message_tokens(msg)
                    if msg_tokens <= budget:
                        budget -= msg_tokens
                        selected_older_indices.add(msg_idx)

        # Step 8 — Assemble final context (chronological order)
        final_context = [
            msg for i, msg in enumerate(older_messages)
            if i in selected_older_indices
        ]
        final_context.extend(recent_messages)
        return final_context

    @staticmethod
    def _min_max_scale(scores: np.ndarray) -> np.ndarray:
        """Normalise an array to [0, 1] via min-max scaling."""
        if len(scores) == 0:
            return scores
        min_val = np.min(scores)
        max_val = np.max(scores)
        if max_val > min_val:
            return (scores - min_val) / (max_val - min_val)
        return np.zeros_like(scores)
