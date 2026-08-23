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
from typing import Any, Optional

import streamlit as st
import yaml

from dalal_ai.browser.browser_manager import BrowserManager
from dalal_ai.core.context_manager import ContextManager
from dalal_ai.core.flagged_context_manager import FlaggedContextManager
from dalal_ai.core.orchestrator import Orchestrator
from dalal_ai.core.swarm_orchestrator import SwarmOrchestrator
from utils.exceptions import BrowserActionRequired, ResponseCaptureTimeout
from utils.paths import get_config_path, get_history_path, init_user_data, get_user_data_dir
from utils.logger import logger

# ── Constants ─────────────────────────────────────────────────────────────────

PLATFORM_LABELS = {
    "chatgpt": "ChatGPT",
    "claude": "Claude",
    "gemini": "Gemini",
    "deepseek": "DeepSeek",
    "kimi": "Kimi",
    "huggingchat": "HuggingChat",
    "metaai": "Meta AI",
}

PLATFORM_EMOJI = {
    "chatgpt": "🟢",
    "claude": "🟠",
    "gemini": "🔵",
    "deepseek": "🟣",
    "kimi": "🌙",
    "huggingchat": "🤗",
    "metaai": "♾️",
}

PLATFORM_COLORS = {
    "chatgpt": "#10a37f",
    "claude": "#d4a274",
    "gemini": "#4285f4",
    "deepseek": "#7c3aed",
    "kimi": "#0a0a0a",
    "huggingchat": "#ffcf4d",
    "metaai": "#0064e0",
}


def load_config() -> dict[str, Any]:
    init_user_data()
    config_path = get_config_path()
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def init_session_state(config: dict[str, Any]) -> None:
    if "initialized" in st.session_state:
        return

    history_path = get_history_path()
    st.session_state.context = ContextManager(persist_path=history_path)
    st.session_state.config = config
    st.session_state.platforms = list(config["platforms"].keys())
    st.session_state.active_model = st.session_state.platforms[0]
    st.session_state.pending_model_switch = None
    st.session_state.selected_red_ids = []
    st.session_state.browser = None
    st.session_state.orchestrator = None
    st.session_state.flagged_mgr = FlaggedContextManager()
    st.session_state.connected = False
    st.session_state.connection_error = ""
    st.session_state.status_log = []
    st.session_state.pending_manual = None
    st.session_state.last_send_error = ""
    st.session_state.swarm_orchestrator = None
    st.session_state.swarm_mode = False
    st.session_state.swarm_moderator = "chatgpt"
    st.session_state.retry_action = None
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
        st.session_state.swarm_orchestrator = SwarmOrchestrator(
            browser,
            st.session_state.context,
        )
        st.session_state.connected = True
        st.session_state.connection_error = ""
        logger.info("Browser connected and Orchestrator created.")
    except Exception as exc:
        st.session_state.browser = None
        st.session_state.orchestrator = None
        st.session_state.connected = False
        st.session_state.connection_error = str(exc)
        logger.error(f"Failed to connect browser: {exc}")


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


def render_flag_controls(index: int, msg: dict[str, Any]) -> None:
    flag = msg.get("flag")
    c1, c2, c3, c4 = st.columns([1, 1, 1, 14])
    
    def toggle_green():
        new_flag = None if flag == "green" else "green"
        st.session_state.context.update_flag(index, new_flag)
        
    def toggle_red():
        new_flag = None if flag == "red" else "red"
        st.session_state.context.update_flag(index, new_flag)
        
    def trigger_retry():
        st.session_state.retry_action = {"index": index, "msg": msg}
        
    with c1:
        icon_g = "🟩" if flag == "green" else "⚪"
        st.button(icon_g, key=f"g_{index}", on_click=toggle_green, help="Toggle Global Context (Green)")
    with c2:
        icon_r = "🟥" if flag == "red" else "⚪"
        st.button(icon_r, key=f"r_{index}", on_click=toggle_red, help="Toggle On-Demand Context (Red)")
    with c3:
        is_last = (index == len(st.session_state.context.messages) - 1)
        if msg["role"] == "assistant" or is_last:
            st.button("🔄", key=f"retry_{index}", on_click=trigger_retry, help="Retry Fetching Response")


def render_message(index: int, msg: dict[str, Any]) -> None:
    """Render a chat message with full Markdown + LaTeX support and flag controls."""
    role = msg["role"]
    content = msg["content"]
    model = msg.get("model", "")
    flag = msg.get("flag")
    swarm_role = msg.get("swarm_role")

    if role == "user":
        with st.chat_message("user", avatar="👤"):
            render_flag_controls(index, msg)
            if swarm_role == "worker":
                st.caption(f"*(Delegated to Swarm Worker)*")
            if msg.get("files"):
                for f in msg["files"]:
                    st.caption(f"📎 Attached: {os.path.basename(f)}")
            st.markdown(content)
    else:
        if swarm_role == "moderator":
            avatar = "🐝"
            badge = f"**Swarm Mode:** {render_model_badge(model)} is moderating."
        elif swarm_role == "worker":
            avatar = "🐝"
            badge = f"**Swarm Worker:** {render_model_badge(model)}"
        else:
            avatar = "🤖"
            badge = render_model_badge(model)

        with st.chat_message("assistant", avatar=avatar):
            render_flag_controls(index, msg)
            st.markdown(badge, unsafe_allow_html=True)
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

    #MainMenu, footer { visibility: hidden; }

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
            
    # Auto-shutdown logic
    if "auto_shutdown_started" not in st.session_state:
        st.session_state.auto_shutdown_started = True
        import threading
        import time
        import os
        
        def monitor_sessions():
            try:
                # Wait for initial connection to settle
                time.sleep(5)
                empty_count = 0
                while True:
                    time.sleep(2)
                    try:
                        from streamlit.runtime import get_instance
                        runtime = get_instance()
                        if hasattr(runtime, '_session_mgr'):
                            sessions = runtime._session_mgr.list_active_sessions()
                            count = len(sessions)
                        else:
                            count = 1 # Fallback if API changes
                    except Exception:
                        count = 1
                        
                    if count == 0:
                        empty_count += 1
                        if empty_count >= 3: # ~6 seconds of 0 active sessions
                            try:
                                # Ensure playwright cleans up if we can reach it
                                if 'browser' in st.session_state and st.session_state.browser:
                                    st.session_state.browser.disconnect()
                            except Exception:
                                pass
                            os._exit(0)
                    else:
                        empty_count = 0
            except Exception:
                pass
                
        thread = threading.Thread(target=monitor_sessions, daemon=True)
        try:
            from streamlit.runtime.scriptrunner import add_script_run_ctx
            add_script_run_ctx(thread)
        except Exception:
            pass
        thread.start()

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
    )
    
    if selected != st.session_state.active_model:
        st.warning(f"Pending Switch to {selected}")
        delivered = st.session_state.flagged_mgr.session_delivered.get(selected, set())
        available_reds = [(i, m) for i, m in enumerate(st.session_state.context.messages) if m.get("flag") == "red" and i not in delivered]
        
        selected_red_ids = []
        if available_reds:
            st.markdown("**Select red context to attach:**")
            for i, m in available_reds:
                preview = m["content"][:40] + ("..." if len(m["content"]) > 40 else "")
                if st.checkbox(f"[{i}] {preview}", key=f"attach_{i}_{selected}"):
                    selected_red_ids.append(i)
        else:
            st.caption("No red-flagged messages available.")
            
        if st.button("Confirm Switch", type="primary", use_container_width=True):
            st.session_state.active_model = selected
            st.session_state.selected_red_ids = selected_red_ids
            st.rerun()
    else:
        st.markdown(render_model_badge(st.session_state.active_model), unsafe_allow_html=True)

    st.divider()
    st.session_state.swarm_mode = st.sidebar.toggle("🐝 Enable Swarm Mode", st.session_state.swarm_mode)
    if st.session_state.swarm_mode:
        st.session_state.swarm_moderator = st.sidebar.selectbox(
            "Moderator AI",
            st.session_state.platforms,
            index=st.session_state.platforms.index(st.session_state.swarm_moderator) if st.session_state.swarm_moderator in st.session_state.platforms else 0,
            format_func=lambda p: platform_labels[p],
        )
        
        st.sidebar.markdown("**Swarm Workers**")
        worker_count = st.sidebar.number_input("Number of Workers", min_value=1, max_value=10, value=len(st.session_state.platforms))
        workers = []
        for i in range(worker_count):
            # Default to spreading across platforms if possible, otherwise first platform
            default_idx = i % len(st.session_state.platforms)
            w = st.sidebar.selectbox(
                f"Worker {i+1}", 
                st.session_state.platforms, 
                index=default_idx,
                key=f"swarm_worker_{i}", 
                format_func=lambda p: platform_labels[p]
            )
            workers.append(w)
        st.session_state.swarm_workers = workers
        
        if st.sidebar.button("Pre-launch Swarm Tabs"):
            with st.spinner("Pre-launching tabs in browser..."):
                counts = {}
                # Include moderator in tab count so it gets a tab too
                counts[st.session_state.swarm_moderator] = 1
                for w in st.session_state.swarm_workers:
                    counts[w] = counts.get(w, 0) + 1
                    
                for platform, count in counts.items():
                    try:
                        st.session_state.orchestrator.browser.prelaunch_tabs(platform, count)
                    except Exception as exc:
                        st.sidebar.error(f"Failed to launch {platform}: {exc}")
                st.sidebar.success("Swarm tabs ready!")

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
    
    # Flag Stats
    green_msgs = [m for m in st.session_state.context.messages if m.get("flag") == "green"]
    red_msgs = [m for m in st.session_state.context.messages if m.get("flag") == "red"]
    green_tokens = sum(int(len(m["content"].split()) * 1.3) for m in green_msgs)
    red_tokens = sum(int(len(m["content"].split()) * 1.3) for m in red_msgs)

    st.markdown(f"**🟩 Green:** {len(green_msgs)} msgs (~{green_tokens} tokens)")
    st.markdown(f"**🟥 Red:** {len(red_msgs)} msgs (~{red_tokens} tokens)")
    if green_tokens > 4000:
        st.warning("Green context may be too large for some models (>4000 tokens).")

    st.divider()

    # Context Delivery Status
    st.markdown("### Context Delivery Status")
    delivered = st.session_state.flagged_mgr.session_delivered
    if delivered:
        for model_name, indices in delivered.items():
            if indices:
                st.caption(f"**{model_name}**: {len(indices)} messages delivered (Indices: {', '.join(map(str, sorted(indices)))})")
            if st.button(f"Reset {model_name} Context", key=f"reset_ctx_{model_name}"):
                st.session_state.flagged_mgr.reset_model_context(model_name)
                st.rerun()
    else:
        st.caption("No context delivered yet.")

    st.divider()

    if st.button("🗑️ Clear Conversation", use_container_width=True):
        st.session_state.context.clear()
        st.session_state.pending_manual = None
        st.rerun()

    if st.button("💾 Export Session", use_container_width=True):
        export_dir = st.session_state.config.get("export_directory", "exports")
        export_dir_full = os.path.join(get_user_data_dir(), export_dir)
        j_path, m_path = st.session_state.context.export_session(export_dir_full)
        st.toast(f"Exported to {export_dir_full}")

    if st.session_state.connected and st.session_state.browser:
        with st.expander("Open Browser Tabs"):
            for tab in st.session_state.browser.list_open_tabs():
                st.caption(f"**{tab['title'][:40]}**")
                st.caption(tab["url"][:70])

# ── Auto-connect on first load ────────────────────────────────────────────────
if not st.session_state.connected and not st.session_state.connection_error:
    connect_browser()

# Process any pending retry action
if st.session_state.get("retry_action"):
    action = st.session_state.retry_action
    st.session_state.retry_action = None
    
    idx = action["index"]
    retry_msg = action["msg"]
    platform = retry_msg.get("model")
    
    if platform and st.session_state.orchestrator:
        with st.spinner(f"Retrying fetch from {platform}..."):
            try:
                response = st.session_state.orchestrator.browser.extract_stable_response(platform)
                if retry_msg["role"] == "assistant":
                    st.session_state.context.update_message_content(idx, response)
                else:
                    st.session_state.context.add_message("assistant", response, model=platform)
                
                if st.session_state.pending_manual and st.session_state.pending_manual.get("platform") == platform:
                    st.session_state.pending_manual = None
                
                st.rerun()
            except Exception as exc:
                st.error(f"Retry failed: {exc}")

# ── Main chat area ────────────────────────────────────────────────────────────
st.markdown("### Chat")
st.caption(
    "Responses render with **Markdown**, **code blocks**, and **LaTeX** "
    "(inline `$E=mc^2$` or block `$$\\int_0^1 x^2\\,dx$$`)."
)

# Render conversation history
for i, msg in enumerate(st.session_state.context.messages):
    render_message(i, msg)

# Smart Flagging Assist
if len(st.session_state.context.messages) == 2 and not st.session_state.get('flag_assist_shown', False):
    st.info("Suggestion: Set your first message as global context (green flag) so it's always included when switching models.")
    col1, col2 = st.columns([2, 10])
    with col1:
        if st.button("Set Green Flag", key="assist_green"):
            st.session_state.context.update_flag(0, "green")
            st.session_state.flag_assist_shown = True
            st.rerun()
    with col2:
        if st.button("Dismiss", key="assist_dismiss"):
            st.session_state.flag_assist_shown = True
            st.rerun()

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
    pending_switch = selected != st.session_state.active_model
    
    prompt = st.chat_input(
        "Type your message…",
        accept_file="multiple",
        disabled=bool(pending) or pending_switch,
    )
    if pending:
        st.info("Save or clear the pending response before sending another message.")
    elif pending_switch:
        st.info("Confirm the model switch in the sidebar before sending a message.")
    if prompt:
        # Clear any previous error
        st.session_state.last_send_error = ""

        # Streamlit 1.37+ chat_input returns a dict-like object when accept_file is used
        if isinstance(prompt, str):
            user_input = prompt
            uploaded_files = []
        else:
            user_input = prompt.text
            uploaded_files = prompt.files or []

        saved_files = []
        if uploaded_files:
            import os
            from utils.paths import get_attachments_dir
            attach_dir = get_attachments_dir()
            for uf in uploaded_files:
                file_path = os.path.join(attach_dir, uf.name)
                with open(file_path, "wb") as f:
                    f.write(uf.getvalue())
                saved_files.append(file_path)

        if not user_input.strip() and saved_files:
            user_input = "Please refer to the attached files."

        with st.chat_message("user", avatar="👤"):
            if saved_files:
                for f in saved_files:
                    st.caption(f"📎 Attached: {os.path.basename(f)}")
            st.markdown(user_input)

        if st.session_state.swarm_mode:
            with st.chat_message("assistant", avatar="🐝"):
                st.markdown(f"**Swarm Mode:** {render_model_badge(st.session_state.swarm_moderator)} is moderating.", unsafe_allow_html=True)
                success = False
                try:
                    with st.status("Swarm active... Delegating to workers.", expanded=True) as status:
                        for update in st.session_state.swarm_orchestrator.execute_swarm_task(
                            user_input, 
                            st.session_state.swarm_moderator,
                            workers=st.session_state.swarm_workers,
                            flagged_mgr=st.session_state.flagged_mgr,
                            selected_red_ids=st.session_state.selected_red_ids,
                            files=saved_files
                        ):
                            if update["type"] == "status":
                                status.update(label=update["message"])
                                st.write(update["message"])
                            elif update["type"] == "complete":
                                status.update(label="Swarm Task Complete!", state="complete")
                                final_answer = update["answer"]
                    st.markdown(final_answer)
                    st.session_state.selected_red_ids = []
                    success = True
                except Exception as exc:
                    st.error(f"Swarm execution failed: {exc}")
        else:
            with st.chat_message("assistant", avatar="🤖"):
                platform = st.session_state.active_model
                st.markdown(render_model_badge(platform), unsafe_allow_html=True)

                success = False
                try:
                    with st.spinner(f"Sending to {PLATFORM_LABELS.get(platform, platform)}… (watch the browser tab)"):
                        response = st.session_state.orchestrator.send_message(
                            platform,
                            user_input,
                            flagged_mgr=st.session_state.flagged_mgr,
                            selected_red_ids=st.session_state.selected_red_ids,
                            files=saved_files
                        )
                    st.markdown(response)
                    # Clear red flags after successful send
                    st.session_state.selected_red_ids = []
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
