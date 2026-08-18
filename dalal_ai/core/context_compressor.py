"""
Context Compressor — semantic token-budget compression for chat history.

Legacy algorithmic fallback used when the user has set zero manual flags.
Combines TextRank (structural centrality) and BM25 (query relevance) to
select the most important older messages that fit within a token budget.
"""

from __future__ import annotations

import math
from typing import Any

from utils.logger import logger


class ContextCompressor:
    """
    Compresses chat history into a subset of important messages to fit a token budget.

    Uses TF-IDF, TextRank for structural importance, and BM25 for query relevance.
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
        return int(len(text.split()) * 1.3)

    def _estimate_message_tokens(self, message: dict[str, Any]) -> int:
        return self._estimate_tokens(message.get("content", ""))

    def build_context(
        self, chat_history: list[dict[str, Any]], current_query: str
    ) -> list[dict[str, Any]]:
        if len(chat_history) <= self.recent_count:
            return chat_history.copy()

        recent_messages = chat_history[-self.recent_count:]
        older_messages = chat_history[:-self.recent_count]

        recent_tokens = sum(self._estimate_message_tokens(msg) for msg in recent_messages)
        query_tokens = self._estimate_tokens(current_query)
        budget = self.max_tokens - recent_tokens - query_tokens

        if budget <= 0:
            logger.warning("ContextCompressor: Token budget too small. Only returning recent messages.")
            return recent_messages.copy()

        older_chunks: list[str] = []
        chunk_mappings: list[list[int]] = []
        for i in range(0, len(older_messages), self.chunk_size):
            chunk_msgs = older_messages[i:i + self.chunk_size]
            chunk_text = " ".join(msg.get("content", "") for msg in chunk_msgs)
            older_chunks.append(chunk_text)
            chunk_mappings.append(list(range(i, min(i + self.chunk_size, len(older_messages)))))

        recent_text_chunks = [msg.get("content", "") for msg in recent_messages]
        all_chunks = older_chunks + recent_text_chunks

        # TF-IDF
        tokenized = [c.split() for c in all_chunks]
        df = {}
        for t in tokenized:
            for term in set(t):
                df[term] = df.get(term, 0) + 1
        
        N = len(all_chunks)
        if N == 0:
            return recent_messages.copy()
            
        idf = {term: math.log((N + 1) / (df[term] + 1)) + 1 for term in df}
        
        tfidf_vecs = []
        for t in tokenized:
            vec = {}
            for term in t:
                vec[term] = vec.get(term, 0) + 1
            norm = 0.0
            for term in vec:
                vec[term] = vec[term] * idf[term]
                norm += vec[term] ** 2
            norm = math.sqrt(norm)
            if norm > 0:
                for term in vec:
                    vec[term] /= norm
            tfidf_vecs.append(vec)

        # TextRank
        sim_matrix = [[0.0] * N for _ in range(N)]
        for i in range(N):
            for j in range(N):
                if i != j:
                    sim = 0.0
                    for term in tfidf_vecs[i]:
                        if term in tfidf_vecs[j]:
                            sim += tfidf_vecs[i][term] * tfidf_vecs[j][term]
                    if sim >= self.edge_threshold:
                        sim_matrix[i][j] = sim

        # Stochastic transition
        transition = [[0.0] * N for _ in range(N)]
        for i in range(N):
            row_sum = sum(sim_matrix[i])
            if row_sum == 0:
                transition[i][i] = 1.0
            else:
                for j in range(N):
                    transition[i][j] = sim_matrix[i][j] / row_sum

        # PageRank
        d = 0.85
        pr = [1.0 / N] * N
        for _ in range(30):
            new_pr = [(1 - d) / N] * N
            for j in range(N):
                for i in range(N):
                    new_pr[j] += d * transition[i][j] * pr[i]
            
            diff = sum((new_pr[i] - pr[i])**2 for i in range(N))**0.5
            pr = new_pr
            if diff < 1e-6:
                break

        textrank_scores = pr[:len(older_chunks)]

        # BM25
        bm25_scores = [0.0] * len(older_chunks)
        if current_query.strip():
            k1 = 1.5
            b = 0.75
            tokenized_query = current_query.split()
            doc_lengths = [len(t) for t in tokenized]
            avgdl = sum(doc_lengths) / max(len(doc_lengths), 1)
            avgdl = max(avgdl, 1e-6)

            bm25_idf = {}
            for term, freq in df.items():
                bm25_idf[term] = math.log((N - freq + 0.5) / (freq + 0.5) + 1.0)

            for i, chunk_text in enumerate(older_chunks):
                chunk_tokens = chunk_text.split()
                score = 0.0
                dl = len(chunk_tokens)
                for q_term in tokenized_query:
                    if q_term in bm25_idf:
                        tf = chunk_tokens.count(q_term)
                        score += bm25_idf[q_term] * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / avgdl))
                bm25_scores[i] = score

        # Scaling
        tr_scaled = self._min_max_scale(textrank_scores)
        if current_query.strip():
            bm25_scaled = self._min_max_scale(bm25_scores)
            final_scores = [self.alpha * tr + (1 - self.alpha) * bm for tr, bm in zip(tr_scaled, bm25_scaled)]
        else:
            final_scores = tr_scaled

        # Selection
        sorted_indices = sorted(range(len(final_scores)), key=lambda k: final_scores[k], reverse=True)
        selected_older_indices: set[int] = set()

        for idx in sorted_indices:
            chunk_msgs = [older_messages[msg_idx] for msg_idx in chunk_mappings[idx]]
            chunk_tokens = sum(self._estimate_message_tokens(msg) for msg in chunk_msgs)

            if chunk_tokens <= budget:
                budget -= chunk_tokens
                selected_older_indices.update(chunk_mappings[idx])
            else:
                for msg_idx in chunk_mappings[idx]:
                    msg = older_messages[msg_idx]
                    msg_tokens = self._estimate_message_tokens(msg)
                    if msg_tokens <= budget:
                        budget -= msg_tokens
                        selected_older_indices.add(msg_idx)

        final_context = [
            msg for i, msg in enumerate(older_messages)
            if i in selected_older_indices
        ]
        final_context.extend(recent_messages)
        return final_context

    @staticmethod
    def _min_max_scale(scores: list[float]) -> list[float]:
        if not scores:
            return scores
        min_val = min(scores)
        max_val = max(scores)
        if max_val > min_val:
            return [(s - min_val) / (max_val - min_val) for s in scores]
        return [0.0] * len(scores)
