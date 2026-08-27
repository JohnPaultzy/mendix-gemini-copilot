import os
import streamlit as st
import streamlit.components.v1 as components
import uuid
import re
import sqlite3
import config
from core.chat_manager import (
    init_db, create_session, get_all_sessions, 
    get_session_messages, add_message, delete_session,
    delete_single_message, branch_session_from_message
)
from core.mendix_parser import parse_uploaded_files, parse_uploaded_file, get_project_scss_context, scan_mendix_folder
from core.gemini_client import get_gemini_client, stream_chat_response

# Safe Import / Fallback para sa update_session_title (Zero Crash Guarantee)
try:
    from core.chat_manager import update_session_title
except ImportError:
    def update_session_title(session_id, new_title):
        db_path = os.path.join(os.path.dirname(__file__), "storage", "chats.db")
        conn = sqlite3.connect(db_path, timeout=30.0)
        try:
            cursor = conn.cursor()
            cursor.execute("UPDATE sessions SET title = ? WHERE id = ?", (new_title.strip(), session_id))
            conn.commit()
        finally:
            conn.close()

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
div[data-testid="stVerticalBlock"] > div:has(div.sticky-header-marker) {
    position: sticky;
    top: 2.875rem;
    background-color: rgba(14, 17, 23, 0.95);
    backdrop-filter: blur(8px);
    z-index: 99;
    padding: 10px 0 15px 0;
    border-bottom: 1px solid rgba(250, 250, 250, 0.1);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.25);
}

.main .block-container {
    padding-bottom: 140px !important;
}

.stChatMessage {
    padding: 1rem;
    border-radius: 0.5rem;
    margin-bottom: 0.5rem;
}

.attached-badge {
    background-color: #1e293b;
    border: 1px solid #334155;
    padding: 4px 10px;
    border-radius: 6px;
    font-size: 0.82rem;
    color: #94a3b8;
    margin-top: 6px;
    display: inline-block;
}

div:has(> iframe[title="core.chat_input_component.mendix_unified_chat"]) {
    position: fixed !important;
    bottom: 0 !important;
    left: 0 !important;
    right: 0 !important;
    z-index: 1000 !important;
    background: linear-gradient(180deg, rgba(14,17,23,0) 0%, rgba(14,17,23,0.95) 25%, rgba(14,17,23,1) 100%) !important;
    padding: 10px calc((100vw - 900px) / 2) 15px calc((100vw - 900px) / 2) !important;
}

@media (max-width: 992px) {
    div:has(> iframe[title="core.chat_input_component.mendix_unified_chat"]) {
        padding: 10px 1rem 15px 1rem !important;
    }
}
</style>
""", unsafe_allow_html=True)

# 4. Session State Setup
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())

if "last_processed_ts" not in st.session_state:
    st.session_state.last_processed_ts = 0

if "system_prompt" not in st.session_state:
    st.session_state.system_prompt = config.SYSTEM_PROMPT_PRESETS["🛡️ Senior Mendix Architect (Strict Best Practices & SOD)"]

if "branch_toast" in st.session_state:
    st.toast(st.session_state.pop("branch_toast"), icon="🔀")

# 5. SIDEBAR
with st.sidebar:
    st.title("⚡ Mendix Copilot")
    
    if st.button("➕ New Chat", use_container_width=True, type="primary"):
        st.session_state.session_id = str(uuid.uuid4())
        st.rerun()
        
    st.divider()
    
    # Model Selection
    model_options = [
        "gemini-3.7-flash",
        "gemini-2.5-flash",
        "gemini-2.5-pro",
        "gemini-1.5-flash"
    ]
    default_model_idx = model_options.index(config.DEFAULT_MODEL) if config.DEFAULT_MODEL in model_options else 0
    
    model_choice = st.selectbox(
        "🤖 Gemini Model",
        options=model_options,
        index=default_model_idx
    )
    
    # System Instructions
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
        help="Upload .md files containing coding standards, PRD, or company rules."
    )
    
    st.divider()
    
    # Mendix Project Folder Input
    st.subheader("📂 Mendix Project Path")
    project_path = st.text_input("Local Folder Path", placeholder="e.g. C:/MendixProjects/ProcureFlow")
    
    st.divider()
    
    # Chat History List (Rename ✏️ ug Delete 🗑️)
    st.subheader("💬 Chat History")
    sessions = get_all_sessions()
        
    for s_id, s_title, _ in sessions:
        col1, col2, col3 = st.columns([0.64, 0.18, 0.18])
        with col1:
            is_active = (s_id == st.session_state.session_id)
            label = f"👉 {s_title}" if is_active else f"📄 {s_title}"
            if st.button(label, key=f"btn_{s_id}", use_container_width=True):
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
            horizontal=True
        )
    with col_m2:
        uploaded_files = st.file_uploader(
            "📎 Attach Files (Page .MPK, Screenshots, .MD, SCSS, XML)",
            type=["png", "jpg", "jpeg", "xml", "json", "txt", "mpk", "scss", "css", "md"],
            accept_multiple_files=True,
            help="Pwede ka mag-drag & drop og daghang screenshots, .mpk packages, ug scss files dungan!"
        )

# 7. RENDER CHAT MESSAGES
messages = get_session_messages(st.session_state.session_id)
for msg in messages:
    msg_id = msg["id"]
    role = msg["role"]
    content = msg["content"]
    
    with st.chat_message(role):
        st.markdown(content, unsafe_allow_html=True)
        
        if role == "assistant" and "```html" in content:
            html_blocks = re.findall(r'```html(.*?)```', content, re.DOTALL)
            for idx, html_code in enumerate(html_blocks):
                st.caption(f"👁️ **Live Visual UI Preview #{idx+1}:**")
                components.html(html_code.strip(), height=680, scrolling=True)
        
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

# 8. INVISIBLE ANCHOR & AUTO-SCROLL CONTROLLER
st.markdown('<div id="chat-bottom-anchor" style="height: 1px; margin-bottom: 20px;"></div>', unsafe_allow_html=True)

autoscroll_js = """
<script>
(function() {
    function scrollToBottom() {
        try {
            const pDoc = window.parent.document;
            if (!pDoc) return;
            
            const anchor = pDoc.getElementById('chat-bottom-anchor');
            if (anchor) {
                anchor.scrollIntoView({ behavior: 'smooth', block: 'end' });
            }
            
            const mainSec = pDoc.querySelector('section.main') || pDoc.querySelector('div[data-testid="stMain"]');
            if (mainSec) {
                mainSec.scrollTop = mainSec.scrollHeight;
            }
        } catch(e) {}
    }
    
    setTimeout(scrollToBottom, 100);
    setTimeout(scrollToBottom, 300);
    setTimeout(scrollToBottom, 600);
})();
</script>
"""
components.html(autoscroll_js, height=0)

# 9. UNIFIED PINNED CHATBOX (Pinned to Bottom)
chat_payload = custom_chat_box(key=f"unified_chat_{st.session_state.session_id}")

# 10. PROCESS SUBMITTED MESSAGE & EXECUTION
if chat_payload and isinstance(chat_payload, dict):
    msg_ts = chat_payload.get("timestamp", 0)
    
    if msg_ts > st.session_state.last_processed_ts:
        st.session_state.last_processed_ts = msg_ts
        
        user_prompt_text = chat_payload.get("text", "").strip()
        pasted_imgs = chat_payload.get("images", [])
        
        create_session(st.session_state.session_id, "New Chat", st.session_state.system_prompt)
        
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
                        response_placeholder.markdown(full_response + "▌")
                        
                    response_placeholder.markdown(full_response)
                    
                    if "```html" in full_response:
                        html_blocks = re.findall(r'```html(.*?)```', full_response, re.DOTALL)
                        for idx, html_code in enumerate(html_blocks):
                            st.caption(f"👁️ **Live Visual UI Preview #{idx+1}:**")
                            components.html(html_code.strip(), height=680, scrolling=True)
                    
                    add_message(st.session_state.session_id, "assistant", full_response)
                    st.rerun()
                    
                except Exception as e:
                    st.error(f"Error communicating with Gemini: {str(e)}")