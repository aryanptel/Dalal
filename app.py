"""
AI Web Chat Orchestrator — Browser UI
======================================

Streamlit web interface for routing prompts across ChatGPT, Claude, Gemini,
and DeepSeek with rich Markdown and LaTeX rendering.

Run:
    streamlit run app.py
"""

from __future__ import annotations

import os
from typing import Any

import streamlit as st
import yaml

from browser_manager import BrowserManager
from context_manager import ContextManager
from orchestrator import Orchestrator
from utils.exceptions import BrowserActionRequired, ResponseCaptureTimeout

# ── Constants ─────────────────────────────────────────────────────────────────
CONFIG_FILE = "config.yaml"
HISTORY_FILE = "chat_history.json"

PLATFORM_LABELS = {
    "chatgpt": "ChatGPT",
    "claude": "Claude",
    "gemini": "Gemini",
    "deepseek": "DeepSeek",
}

PLATFORM_EMOJI = {
    "chatgpt": "🟢",
    "claude": "🟠",
    "gemini": "🔵",
    "deepseek": "🟣",
}

PLATFORM_COLORS = {
    "chatgpt": "#10a37f",
    "claude": "#d4a274",
    "gemini": "#4285f4",
    "deepseek": "#7c3aed",
}


def load_config() -> dict[str, Any]:
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), CONFIG_FILE)
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def init_session_state(config: dict[str, Any]) -> None:
    if "initialized" in st.session_state:
        return

    history_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), HISTORY_FILE)
    st.session_state.context = ContextManager(persist_path=history_path)
    st.session_state.config = config
    st.session_state.platforms = list(config["platforms"].keys())
    st.session_state.active_model = st.session_state.platforms[0]
    st.session_state.browser = None
    st.session_state.orchestrator = None
    st.session_state.connected = False
    st.session_state.connection_error = ""
    st.session_state.status_log = []
    st.session_state.pending_manual = None
    st.session_state.last_send_error = ""
    st.session_state.initialized = True


def connect_browser() -> None:
    """Connect to the browser and create the orchestrator."""
    config = st.session_state.config
    st.session_state.status_log = []
    status_log = st.session_state.status_log

    def on_status(msg: str) -> None:
        # The browser worker must not access Streamlit's thread-local session
        # state.  It can safely append to this list captured on the script
        # thread; Streamlit reads it after the blocking browser call returns.
        status_log.append(msg)

    browser = BrowserManager(config, on_status=on_status)
    try:
        browser.connect()
        st.session_state.browser = browser
        st.session_state.orchestrator = Orchestrator(
            browser,
            st.session_state.context,
            config,
            on_status=on_status,
        )
        st.session_state.connected = True
        st.session_state.connection_error = ""
    except Exception as exc:
        st.session_state.browser = None
        st.session_state.orchestrator = None
        st.session_state.connected = False
        st.session_state.connection_error = str(exc)


def render_model_badge(model: str) -> str:
    label = PLATFORM_LABELS.get(model, model.title())
    emoji = PLATFORM_EMOJI.get(model, "🤖")
    color = PLATFORM_COLORS.get(model, "#5b8cff")
    return (
        f'<span style="display:inline-block;padding:3px 10px;border-radius:999px;'
        f'font-size:0.75rem;font-weight:600;color:{color};'
        f'background:{color}22;border:1px solid {color}44;">'
        f'{emoji} {label}</span>'
    )


def render_message(msg: dict[str, Any]) -> None:
    """Render a chat message with full Markdown + LaTeX support."""
    role = msg["role"]
    content = msg["content"]
    model = msg.get("model", "")

    if role == "user":
        with st.chat_message("user", avatar="👤"):
            st.markdown(content)
    else:
        with st.chat_message("assistant", avatar="🤖"):
            st.markdown(render_model_badge(model), unsafe_allow_html=True)
            st.markdown(content)


# ── Page config & styling ─────────────────────────────────────────────────────
st.set_page_config(
    page_title="AI Web Orchestrator",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    html, body, [data-testid="stAppViewContainer"] {
        font-family: 'Inter', sans-serif !important;
    }

    #MainMenu, footer, header { visibility: hidden; }

    section[data-testid="stSidebar"] {
        background: #111827 !important;
        border-right: 1px solid #2a3050;
    }

    .hero-title {
        background: linear-gradient(135deg, #5b8cff, #8b5cf6, #f472b6);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-size: 1.6rem;
        font-weight: 700;
        margin: 0;
    }

    .hero-sub {
        color: #8b93a8;
        font-size: 0.85rem;
        margin-top: 4px;
    }

    .status-ok { color: #34d399; font-size: 0.85rem; }
    .status-err { color: #f87171; font-size: 0.85rem; }

    .stat-card {
        background: #1a1f35;
        border: 1px solid #2a3050;
        border-radius: 10px;
        padding: 12px;
        text-align: center;
    }
    .stat-value {
        font-size: 1.4rem;
        font-weight: 700;
        color: #e8eaf0;
    }
    .stat-label {
        font-size: 0.7rem;
        color: #8b93a8;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }

    /* Improve math and code readability */
    [data-testid="stChatMessage"] {
        padding: 1rem 1.25rem;
    }
    [data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] {
        font-size: 1rem;
        line-height: 1.7;
    }
    [data-testid="stChatMessage"] p,
    [data-testid="stChatMessage"] li {
        margin-bottom: 0.55rem;
    }
    [data-testid="stChatMessage"] ul,
    [data-testid="stChatMessage"] ol {
        padding-left: 1.5rem;
    }
    .katex-display { margin: 1em 0 !important; overflow-x: auto; }
    [data-testid="stChatMessage"] pre {
        background: #0d1117 !important;
        border-radius: 8px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ── Load config & init ─────────────────────────────────────────────────────────
config = load_config()
init_session_state(config)

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown('<p class="hero-title">🧠 Dalal AI</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="hero-sub">Route prompts across AI web chats. '
        "Equations, code &amp; tables render beautifully.</p>",
        unsafe_allow_html=True,
    )
    st.divider()

    # Connection status
    if st.session_state.connected:
        st.markdown('<p class="status-ok">● Connected to browser</p>', unsafe_allow_html=True)
    else:
        st.markdown('<p class="status-err">● Not connected</p>', unsafe_allow_html=True)
        if st.session_state.connection_error:
            st.error(st.session_state.connection_error)

    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("Connect", use_container_width=True, type="primary"):
            connect_browser()
            st.rerun()
    with col_b:
        if st.button("Disconnect", use_container_width=True):
            if st.session_state.browser:
                st.session_state.browser.disconnect()
            st.session_state.browser = None
            st.session_state.orchestrator = None
            st.session_state.connected = False
            st.session_state.pending_manual = None
            st.rerun()

    st.divider()

    # Model selector
    platform_labels = {
        p: f"{PLATFORM_EMOJI.get(p, '🤖')} {PLATFORM_LABELS.get(p, p.title())}"
        for p in st.session_state.platforms
    }
    selected = st.selectbox(
        "Target Model",
        st.session_state.platforms,
        index=st.session_state.platforms.index(st.session_state.active_model)
        if st.session_state.active_model in st.session_state.platforms
        else 0,
        format_func=lambda p: platform_labels[p],
        key="model_selector",
    )
    st.session_state.active_model = selected
    st.markdown(render_model_badge(selected), unsafe_allow_html=True)

    st.divider()

    # Stats
    stats = st.session_state.context.get_stats()
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(
            f'<div class="stat-card"><div class="stat-value">{stats["total_messages"]}</div>'
            f'<div class="stat-label">Messages</div></div>',
            unsafe_allow_html=True,
        )
    with c2:
        st.markdown(
            f'<div class="stat-card"><div class="stat-value">{stats["total_characters"]:,}</div>'
            f'<div class="stat-label">Chars</div></div>',
            unsafe_allow_html=True,
        )
    with c3:
        st.markdown(
            f'<div class="stat-card"><div class="stat-value">{len(stats["models_used"])}</div>'
            f'<div class="stat-label">Models</div></div>',
            unsafe_allow_html=True,
        )

    if stats["models_used"]:
        st.caption("Used: " + ", ".join(stats["models_used"]))

    st.divider()

    if st.button("🗑️ Clear Conversation", use_container_width=True):
        st.session_state.context.clear()
        st.session_state.pending_manual = None
        st.rerun()

    if st.session_state.connected and st.session_state.browser:
        with st.expander("Open Browser Tabs"):
            for tab in st.session_state.browser.list_open_tabs():
                st.caption(f"**{tab['title'][:40]}**")
                st.caption(tab["url"][:70])

# ── Auto-connect on first load ────────────────────────────────────────────────
if not st.session_state.connected and not st.session_state.connection_error:
    connect_browser()

# ── Main chat area ────────────────────────────────────────────────────────────
st.markdown("### Chat")
st.caption(
    "Responses render with **Markdown**, **code blocks**, and **LaTeX** "
    "(inline `$E=mc^2$` or block `$$\\int_0^1 x^2\\,dx$$`)."
)

# Render conversation history
for msg in st.session_state.context.messages:
    render_message(msg)

# Handle pending manual response (timeout or browser action needed)
pending = st.session_state.pending_manual
if pending:
    st.warning(pending["message"])
    with st.form("manual_response_form", clear_on_submit=True):
        manual_text = st.text_area(
            "Paste the assistant response from the browser",
            height=200,
            placeholder="Copy the model's reply from the browser tab and paste here…",
        )
        submitted = st.form_submit_button("Save Response", type="primary")
        if submitted and manual_text.strip():
            orch = st.session_state.orchestrator
            if pending.get("user_already_sent"):
                orch.complete_manual_response(manual_text.strip())
            else:
                orch.record_manual_response(
                    pending["platform"],
                    pending["user_message"],
                    manual_text.strip(),
                )
            st.session_state.pending_manual = None
            st.rerun()

# Show persistent error if one exists from a previous send attempt
if "last_send_error" in st.session_state and st.session_state.last_send_error:
    st.error(st.session_state.last_send_error)
    if st.button("Dismiss"):
        st.session_state.last_send_error = ""
        st.rerun()

# Chat input
if not st.session_state.connected:
    st.info("Connect to your browser using the sidebar to start chatting.")
else:
    user_input = st.chat_input(
        "Type your message…",
        disabled=bool(pending),
    )
    if pending:
        st.info("Save or clear the pending response before sending another message.")
    if user_input:
        # Clear any previous error
        st.session_state.last_send_error = ""

        with st.chat_message("user", avatar="👤"):
            st.markdown(user_input)

        with st.chat_message("assistant", avatar="🤖"):
            platform = st.session_state.active_model
            st.markdown(render_model_badge(platform), unsafe_allow_html=True)

            success = False
            try:
                with st.spinner(f"Sending to {PLATFORM_LABELS.get(platform, platform)}… (watch the browser tab)"):
                    response = st.session_state.orchestrator.send_message(
                        platform, user_input
                    )
                st.markdown(response)
                success = True

            except BrowserActionRequired as exc:
                st.session_state.pending_manual = {
                    "platform": platform,
                    "user_message": user_input,
                    "user_already_sent": False,
                    "message": (
                        f"**Browser action needed** — {exc.detail}\n\n"
                        "Complete the step in the browser tab, then paste the response below."
                    ),
                }
                st.warning(str(exc))

            except ResponseCaptureTimeout as exc:
                st.session_state.pending_manual = {
                    "platform": platform,
                    "user_message": user_input,
                    "user_already_sent": True,
                    "message": (
                        f"**Response capture timed out** — {exc.detail}\n\n"
                        "Copy the reply from the browser and paste it below."
                    ),
                }
                st.warning(str(exc))

            except Exception as exc:
                # Persist the error so it survives st.rerun()
                import traceback
                error_detail = traceback.format_exc()
                st.session_state.last_send_error = (
                    f"❌ **Error sending to {platform}:**\n\n"
                    f"`{type(exc).__name__}: {exc}`\n\n"
                    f"<details><summary>Full traceback</summary>\n\n"
                    f"```\n{error_detail}\n```\n\n</details>"
                )
                st.error(f"Error: {exc}")

        # Only rerun on success (to refresh history display)
        if success:
            st.rerun()

# Show latest status log in expander (useful during long waits)
status_log = st.session_state.get("status_log", [])
if status_log:
    with st.expander("Latest activity log"):
        for line in status_log[-12:]:
            st.caption(line)
