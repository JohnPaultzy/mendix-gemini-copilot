import os
import streamlit as st
import streamlit.components.v1 as components
import uuid
import re
import sqlite3
from datetime import datetime
import config

# Dynamic Safe Importer para DILI na mo-crash sa ImportError
import core.chat_manager as cm

init_db = getattr(cm, "init_db")
create_session = getattr(cm, "create_session")
get_all_sessions = getattr(cm, "get_all_sessions")
get_session_messages = getattr(cm, "get_session_messages")
add_message = getattr(cm, "add_message")
delete_session = getattr(cm, "delete_session")
delete_single_message = getattr(cm, "delete_single_message")
branch_session_from_message = getattr(cm, "branch_session_from_message")

if hasattr(cm, "update_session_title"):
    update_session_title = cm.update_session_title
else:
    def update_session_title(session_id, new_title):
        db_path = os.path.join(os.path.dirname(__file__), "storage", "chats.db")
        conn = sqlite3.connect(db_path, timeout=30.0)
        try:
            cursor = conn.cursor()
            cursor.execute("UPDATE sessions SET title = ? WHERE id = ?", (new_title.strip(), session_id))
            conn.commit()
        finally:
            conn.close()

if hasattr(cm, "transfer_session_to_new"):
    transfer_session_to_new = cm.transfer_session_to_new
else:
    def transfer_session_to_new(current_session_id, new_session_id):
        db_path = os.path.join(os.path.dirname(__file__), "storage", "chats.db")
        conn = sqlite3.connect(db_path, timeout=30.0)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT title, system_instruction FROM sessions WHERE id = ?", (current_session_id,))
            session_row = cursor.fetchone()
            old_title = session_row[0] if session_row else "Previous Chat"
            sys_prompt = session_row[1] if session_row else ""
            
            new_title = f"⏩ Cont: {old_title[:14]}"
            cursor.execute(
                "INSERT INTO sessions (id, title, system_instruction, created_at) VALUES (?, ?, ?, ?)",
                (new_session_id, new_title, sys_prompt, datetime.now())
            )
            summary_text = f"🔄 **[SESSION TRANSFERRED FROM: '{old_title}']**\n\nNapadayon kini nga panagsultianay gikan sa karaan nga chat session. Ang tanang context sa gi-upload nga Mendix files ug guidelines nagpabilin nga aktibo."
            cursor.execute(
                "INSERT INTO messages (session_id, role, content, has_attachment, created_at) VALUES (?, ?, ?, ?, ?)",
                (new_session_id, "assistant", summary_text, 1, datetime.now())
            )
            conn.commit()
        finally:
            conn.close()

from core.mendix_parser import (
    parse_uploaded_files, parse_uploaded_file, get_project_scss_context,
    scan_mendix_folder, extract_domain_model_mermaid
)
from core.gemini_client import get_gemini_client, stream_chat_response

# 1. Page Configuration
st.set_page_config(
    page_title="Mendix Gemini Copilot",
    page_icon="⚡",
    layout="wide"
)

init_db()

# 2. Declare Custom Component
COMPONENT_PATH = os.path.join(os.path.dirname(__file__), "core", "chat_input_component")
custom_chat_box = components.declare_component("mendix_unified_chat", path=COMPONENT_PATH)

# 3. Custom CSS
st.markdown("""
<style>
/* Sticky Top Controls */
div[data-testid="stVerticalBlock"] > div:has(div.sticky-header-marker) {
    position: sticky;
    top: 2.875rem;
    background-color: rgba(14, 17, 23, 0.95);
    backdrop-filter: blur(8px);
    z-index: 99;
    padding: 6px 0 8px 0;
    border-bottom: 1px solid rgba(250, 250, 250, 0.1);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.25);
}

/* Chat Messages Spacing */
.main .block-container {
    padding-bottom: 100px !important;
    padding-top: 1rem !important;
}

.stChatMessage {
    padding: 0.5rem 0.8rem !important;
    border-radius: 0.5rem !important;
    margin-bottom: 0.2rem !important;
}

div[data-testid="stExpander"] {
    margin-top: 2px !important;
    margin-bottom: 2px !important;
    border: 1px solid #334155 !important;
    border-radius: 6px !important;
}
.streamlit-expanderHeader {
    padding: 3px 8px !important;
    font-size: 0.82rem !important;
    min-height: 1.4rem !important;
}

.attached-badge {
    background-color: #1e293b;
    border: 1px solid #334155;
    padding: 2px 6px;
    border-radius: 5px;
    font-size: 0.78rem;
    color: #94a3b8;
    margin-top: 3px;
    display: inline-block;
}

/* 🔒 Fixed Bottom Wrapper */
div[data-testid="stCustomComponentV1"] {
    position: fixed !important;
    bottom: 0px !important;
    left: 18rem !important;
    right: 0px !important;
    width: calc(100vw - 18rem) !important;
    z-index: 999999 !important;
    background: linear-gradient(180deg, rgba(14,17,23,0) 0%, rgba(14,17,23,0.96) 25%, #0e1117 100%) !important;
    padding: 0px 2rem 6px 2rem !important;
    margin: 0px !important;
    box-sizing: border-box !important;
}

@media (max-width: 992px) {
    div[data-testid="stCustomComponentV1"] {
        left: 0px !important;
        width: 100vw !important;
        padding: 0px 1rem 6px 1rem !important;
    }
}
</style>
""", unsafe_allow_html=True)

# 4. Session State Setup
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())

if "last_processed_ts" not in st.session_state:
    st.session_state.last_processed_ts = 0

if "session_parsed_files" not in st.session_state:
    st.session_state.session_parsed_files = {}

if "system_prompt" not in st.session_state:
    st.session_state.system_prompt = config.SYSTEM_PROMPT_PRESETS["🛡️ Senior Mendix Architect (Strict Best Practices & SOD)"]

if "last_domain_model" not in st.session_state:
    st.session_state.last_domain_model = None

if "branch_toast" in st.session_state:
    st.toast(st.session_state.pop("branch_toast"), icon="🔀")

# 5. SIDEBAR
with st.sidebar:
    st.title("⚡ Mendix Copilot")
    
    col_btn1, col_btn2 = st.columns([0.48, 0.52])
    with col_btn1:
        if st.button("➕ New", use_container_width=True, type="primary"):
            st.session_state.session_id = str(uuid.uuid4())
            st.rerun()
    with col_btn2:
        if st.button("⏩ Continue", help="Start a new chat carrying over context & files", use_container_width=True):
            new_id = str(uuid.uuid4())
            transfer_session_to_new(st.session_state.session_id, new_id)
            current_files = st.session_state.session_parsed_files.get(st.session_state.session_id, [])
            st.session_state.session_parsed_files[new_id] = current_files
            st.session_state.session_id = new_id
            st.session_state.branch_toast = "⏩ Transferred context & files to New Chat!"
            st.rerun()
        
    st.divider()
    
    model_options = [
        "gemini-3.7-flash",
        "gemini-3.5-flash",
        "gemini-3.1-pro-preview",
        "gemini-3.5-flash-lite",
        "gemini-2.5-flash"
    ]
    default_model_idx = model_options.index(config.DEFAULT_MODEL) if config.DEFAULT_MODEL in model_options else 0
    
    model_choice = st.selectbox(
        "🤖 Gemini Model",
        options=model_options,
        index=default_model_idx
    )

    _current_msgs_for_est = get_session_messages(st.session_state.session_id)
    _total_chars = sum(len(m["content"]) for m in _current_msgs_for_est)
    _approx_tokens = _total_chars // 4
    st.caption(f"📊 ~{_approx_tokens:,} tokens estimate (niining chat)")
    
    st.subheader("📝 System Instructions")
    preset_choice = st.selectbox("Prompt Presets", options=list(config.SYSTEM_PROMPT_PRESETS.keys()))
    
    if preset_choice != "✏️ Custom":
        default_text = config.SYSTEM_PROMPT_PRESETS[preset_choice]
    else:
        default_text = st.session_state.system_prompt
        
    system_instruction = st.text_area(
        "Active System Prompt",
        value=default_text,
        height=140
    )
    st.session_state.system_prompt = system_instruction
    
    # 📖 Reference Guide (.MD) Uploader
    st.subheader("📖 Project Guidelines (.md)")
    md_guideline = st.file_uploader(
        "Upload Custom Guidelines (.md)",
        type=["md"],
        key=f"guideline_{st.session_state.session_id}",
        help="Upload .md files containing coding standards, PRD, or company rules."
    )
    
    st.divider()
    
    # Mendix Project Folder Input
    st.subheader("📂 Mendix Project Path")
    project_path = st.text_input("Local Folder Path", placeholder="e.g. C:/MendixProjects/ProcureFlow")
    
    st.divider()
    
    # Chat History List
    st.subheader("💬 Chat History")
    search_query = st.text_input(
        "🔎 Search chat history",
        placeholder="Type to filter by title...",
        key="chat_search_box"
    )
    
    sessions = get_all_sessions()
    if search_query.strip():
        _q = search_query.strip().lower()
        sessions = [s for s in sessions if _q in s[1].lower()]
        if not sessions:
            st.caption("Walay chat nga natugma sa imong search.")
        
    for s_id, s_title, _ in sessions:
        col1, col2, col3 = st.columns([0.64, 0.18, 0.18])
        with col1:
            is_active = (s_id == st.session_state.session_id)
            label = f"👉 {s_title}" if is_active else f"📄 {s_title}"
            if st.button(label, key=f"btn_{s_id}", use_container_width=True, disabled=is_active):
                st.session_state.session_id = s_id
                st.rerun()
        with col2:
            with st.popover("✏️", help="Rename Chat"):
                edit_name = st.text_input("Edit title:", value=s_title, key=f"edit_txt_{s_id}")
                if st.button("Save", key=f"save_title_{s_id}", type="primary", use_container_width=True):
                    if edit_name.strip():
                        update_session_title(s_id, edit_name.strip())
                        st.rerun()
        with col3:
            with st.popover("🗑️", help="Delete Chat"):
                st.write("**Delete chat?**")
                if st.button("Confirm", key=f"confirm_del_{s_id}", type="primary", use_container_width=True):
                    delete_session(s_id)
                    if st.session_state.session_id == s_id:
                        st.session_state.session_id = str(uuid.uuid4())
                    st.rerun()

# 6. STICKY TOP CONTROLS (Main Area)
with st.container():
    st.markdown('<div class="sticky-header-marker"></div>', unsafe_allow_html=True)
    st.header("⚡ Mendix AI Assistant")

    col_m1, col_m2 = st.columns([0.45, 0.55])
    with col_m1:
        scope_mode = st.radio(
            "🔍 Inspection Scope:",
            ["Single Microflow Focus", "Workflow Chain Check", "Full Project Audit"],
            key=f"scope_{st.session_state.session_id}",
            horizontal=True
        )
    with col_m2:
        uploaded_files = st.file_uploader(
            "📎 Attach Files (Page .MPK, Screenshots, .MD, SCSS, XML)",
            type=["png", "jpg", "jpeg", "xml", "json", "txt", "mpk", "scss", "css", "md"],
            accept_multiple_files=True,
            key=f"uploader_{st.session_state.session_id}",
            help="Pwede ka mag-drag & drop og daghang screenshots, .mpk packages, ug scss files dungan!"
        )

# 6b. DOMAIN MODEL DIAGRAM GENERATOR (Mermaid)
with st.expander("🧬 Domain Model Diagram Generator (Beta — gikan sa .mpk)", expanded=False):
    st.caption("I-attach usa o daghang `.mpk` files sa uploader sa taas, unya i-click aron ma-generate ang Entity Relationship diagram (Mermaid).")
    if st.button("🧬 Generate Domain Model Diagram", key="gen_domain_model_btn"):
        mermaid_code, dm_summary = extract_domain_model_mermaid(uploaded_files)
        st.session_state.last_domain_model = (mermaid_code, dm_summary)
        st.rerun()

    if st.session_state.last_domain_model:
        mermaid_code, dm_summary = st.session_state.last_domain_model
        st.caption(dm_summary)
        if mermaid_code:
            mermaid_html = f"""
            <div class="mermaid">{mermaid_code}</div>
            <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
            <script>
                mermaid.initialize({{ startOnLoad: true, theme: 'dark' }});
            </script>
            """
            components.html(mermaid_html, height=450, scrolling=True)
            with st.expander("📄 Raw Mermaid Code", expanded=False):
                st.code(mermaid_code, language="mermaid")

def render_live_preview(html_code, idx):
    st.caption(f"👁️ **Live Visual UI Preview #{idx+1}:**")
    
    auto_resize_script = """
    <script>
    (function() {
        function autoResize() {
            const body = document.body;
            const html = document.documentElement;
            const h = Math.max(body.scrollHeight, body.offsetHeight, html.clientHeight, html.scrollHeight, html.offsetHeight);
            window.parent.postMessage({
                isStreamlitMessage: true,
                type: "streamlit:setFrameHeight",
                height: Math.max(h + 20, 260)
            }, "*");
        }
        window.addEventListener("load", autoResize);
        window.addEventListener("resize", autoResize);
        setTimeout(autoResize, 50);
        setTimeout(autoResize, 200);
        setTimeout(autoResize, 600);
        try {
            new ResizeObserver(autoResize).observe(document.body);
        } catch(e) {}
    })();
    </script>
    """
    clean_html = f"<div style='display:flex; justify-content:center; width:100%; min-height:220px;'>{html_code}</div>" + auto_resize_script
    components.html(clean_html, height=360, scrolling=True)
    
    with st.expander(f"💻 View HTML & CSS Code (#{idx+1})", expanded=False):
        st.code(html_code, language="html")

# 7. RENDER CHAT MESSAGES
messages = get_session_messages(st.session_state.session_id)
for msg in messages:
    msg_id = msg["id"]
    role = msg["role"]
    content = msg["content"]
    
    with st.chat_message(role):
        clean_text_display = re.sub(r'```html.*?```', '', content, flags=re.DOTALL).strip()
        if clean_text_display:
            st.markdown(clean_text_display, unsafe_allow_html=True)
        
        if role == "assistant" and "```html" in content:
            raw_html_blocks = re.findall(r'```html(.*?)```', content, re.DOTALL)
            valid_blocks = [h.strip() for h in raw_html_blocks if len(h.strip()) > 30]
            for idx, html_code in enumerate(valid_blocks):
                render_live_preview(html_code, idx)
        
        with st.expander("⚙️ Message Options", expanded=False):
            btn_col1, btn_col2, _ = st.columns([0.25, 0.35, 0.4])
            
            with btn_col1:
                with st.popover("🗑️ Delete", use_container_width=True):
                    st.write("**Delete this message?**")
                    if st.button("Confirm", key=f"confirm_msg_{msg_id}", type="primary", use_container_width=True):
                        delete_single_message(msg_id)
                        st.rerun()
                    
            with btn_col2:
                if st.button("🔀 Branch from here", key=f"branch_{msg_id}", use_container_width=True):
                    new_branch_id = str(uuid.uuid4())
                    branch_session_from_message(st.session_state.session_id, msg_id, new_branch_id)
                    st.session_state.session_id = new_branch_id
                    st.session_state.branch_toast = "🔀 New branched conversation created successfully!"
                    st.rerun()

needs_resume = (len(messages) > 0 and messages[-1]["role"] == "user")
if needs_resume:
    st.warning("⚠️ Na-interrup ang miaging tubag sa AI niining chata.")
    if st.button("🔄 Resume / Generate Response", type="primary"):
        st.session_state.trigger_resume = True
        st.rerun()

# Auto-Scroll Anchor
st.markdown('<div id="chat-bottom-anchor" style="height: 1px; margin-bottom: 2px;"></div>', unsafe_allow_html=True)
autoscroll_js = """
<script>
(function() {
    function scrollToBottom() {
        try {
            const pDoc = window.parent.document;
            if (!pDoc) return;
            const anchor = pDoc.getElementById('chat-bottom-anchor');
            if (anchor) anchor.scrollIntoView({ behavior: 'smooth', block: 'end' });
            const mainSec = pDoc.querySelector('section.main') || pDoc.querySelector('div[data-testid="stMain"]');
            if (mainSec) mainSec.scrollTop = mainSec.scrollHeight;
        } catch(e) {}
    }
    setTimeout(scrollToBottom, 100);
    setTimeout(scrollToBottom, 300);
    setTimeout(scrollToBottom, 600);
})();
</script>
"""
components.html(autoscroll_js, height=0)

# 8. UNIFIED FIXED BOTTOM CHATBOX
chat_payload = custom_chat_box(key=f"unified_chat_{st.session_state.session_id}")

# 9. PROCESS SUBMISSION & EXECUTION
should_execute = False
user_prompt_text = ""
pasted_imgs = []

if chat_payload and isinstance(chat_payload, dict):
    msg_ts = chat_payload.get("timestamp", 0)
    if msg_ts > st.session_state.last_processed_ts:
        st.session_state.last_processed_ts = msg_ts
        user_prompt_text = chat_payload.get("text", "").strip()
        pasted_imgs = chat_payload.get("images", [])
        should_execute = True

elif st.session_state.get("trigger_resume", False):
    st.session_state.trigger_resume = False
    should_execute = True

if should_execute:
    create_session(st.session_state.session_id, "New Chat", st.session_state.system_prompt)
    
    if not needs_resume or user_prompt_text:
        attached_names = []
        if uploaded_files:
            attached_names.extend([f.name for f in uploaded_files])
        if md_guideline:
            attached_names.append(f"Guideline: {md_guideline.name}")
        if pasted_imgs:
            attached_names.append(f"{len(pasted_imgs)} Pasted Screenshot(s)")
            
        final_user_content = user_prompt_text if user_prompt_text else "(Attached Screenshots/Files)"
        if attached_names:
            final_user_content += f"\n\n<div class='attached-badge'>📎 Attached: {', '.join(attached_names)}</div>"

        with st.chat_message("user"):
            st.markdown(final_user_content, unsafe_allow_html=True)
                
        add_message(st.session_state.session_id, "user", final_user_content, has_attachment=1 if attached_names else 0)
    
    all_files_to_parse = list(uploaded_files) if uploaded_files else []
    if md_guideline:
        all_files_to_parse.append(md_guideline)
        
    attachment_data = parse_uploaded_files(all_files_to_parse, pasted_images_b64=pasted_imgs)
    
    if all_files_to_parse:
        st.session_state.session_parsed_files[st.session_state.session_id] = attachment_data
    else:
        prev_parsed = st.session_state.session_parsed_files.get(st.session_state.session_id, [])
        attachment_data = [item for item in prev_parsed if item.get("type") == "image"]
        if pasted_imgs:
            fresh_img_data = parse_uploaded_files([], pasted_images_b64=pasted_imgs)
            attachment_data.extend(fresh_img_data)
    
    context_info = f"Inspection Scope Mode: {scope_mode}\n"
    if project_path:
        context_info += f"Mendix Local Project Path: {project_path}\n"
        scss_context = get_project_scss_context(project_path)
        if scss_context:
            context_info += scss_context
        if scope_mode == "Full Project Audit":
            context_info += "\n" + scan_mendix_folder(project_path)

    client = get_gemini_client()
    if not client:
        st.error("⚠️ Palihug i-check ang imong GEMINI_API_KEY sa `.env` file!")
    else:
        with st.chat_message("assistant"):
            current_messages = [
                {"role": m["role"], "content": m["content"]}
                for m in get_session_messages(st.session_state.session_id)
            ]
            
            with st.status(f"🧠 Mendix Copilot ({model_choice}) is analyzing & generating...", expanded=True) as status_box:
                response_placeholder = st.empty()
                full_response = ""
                
                try:
                    for chunk in stream_chat_response(
                        client=client,
                        model_name=model_choice,
                        messages_history=current_messages,
                        system_instruction=st.session_state.system_prompt,
                        attachments=attachment_data,
                        context_info=context_info
                    ):
                        full_response += chunk
                        live_text = re.sub(r'```html.*?```', '', full_response, flags=re.DOTALL).strip()
                        response_placeholder.markdown(live_text + "▌")
                        
                    status_box.update(label="✅ Response Ready!", state="complete", expanded=False)
                    final_text = re.sub(r'```html.*?```', '', full_response, flags=re.DOTALL).strip()
                    response_placeholder.markdown(final_text)
                    
                    if "```html" in full_response:
                        raw_html_blocks = re.findall(r'```html(.*?)```', full_response, re.DOTALL)
                        valid_blocks = [h.strip() for h in raw_html_blocks if len(h.strip()) > 30]
                        for idx, html_code in enumerate(valid_blocks):
                            render_live_preview(html_code, idx)
                    
                    add_message(st.session_state.session_id, "assistant", full_response)
                    st.rerun()
                    
                except Exception as e:
                    status_box.update(label="❌ Error Generating Response", state="error", expanded=True)
                    st.error(f"Error communicating with Gemini: {str(e)}")