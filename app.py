import streamlit as st
import streamlit.components.v1 as components
import uuid
import re
import config
from core.chat_manager import (
    init_db, create_session, get_all_sessions, 
    get_session_messages, add_message, delete_session,
    delete_single_message, branch_session_from_message
)
from core.mendix_parser import parse_uploaded_files, parse_uploaded_file, get_project_scss_context, scan_mendix_folder
from core.gemini_client import get_gemini_client, stream_chat_response

# 1. Page Configuration
st.set_page_config(
    page_title="Mendix Gemini Copilot",
    page_icon="⚡",
    layout="wide"
)

init_db()

# 2. Session States Management
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())
    create_session(st.session_state.session_id, "New Chat")

if "system_prompt" not in st.session_state:
    st.session_state.system_prompt = config.SYSTEM_PROMPT_PRESETS["🛡️ Senior Mendix Architect (Strict Best Practices & SOD)"]

# 3. SIDEBAR
with st.sidebar:
    st.title("⚡ Mendix Copilot")
    
    if st.button("➕ New Chat", use_container_width=True, type="primary"):
        new_id = str(uuid.uuid4())
        st.session_state.session_id = new_id
        create_session(new_id, "New Chat", st.session_state.system_prompt)
        st.rerun()
        
    st.divider()
    
    # Model Selection (Naka-default na sa Gemini 3.7 Flash)
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
    
    st.divider()
    
    # Mendix Project Folder Input
    st.subheader("📂 Mendix Project Path")
    project_path = st.text_input("Local Folder Path", placeholder="e.g. C:/MendixProjects/ProcureFlow")
    
    st.divider()
    
    # Chat History List
    st.subheader("💬 Chat History")
    sessions = get_all_sessions()
    for s_id, s_title, _ in sessions:
        col1, col2 = st.columns([0.8, 0.2])
        with col1:
            is_active = (s_id == st.session_state.session_id)
            label = f"👉 {s_title}" if is_active else f"📄 {s_title}"
            if st.button(label, key=f"btn_{s_id}", use_container_width=True):
                st.session_state.session_id = s_id
                st.rerun()
        with col2:
            if st.button("🗑️", key=f"del_{s_id}"):
                delete_session(s_id)
                if st.session_state.session_id == s_id:
                    st.session_state.session_id = str(uuid.uuid4())
                    create_session(st.session_state.session_id, "New Chat")
                st.rerun()

# 4. MAIN CHAT AREA
st.header("⚡ Mendix AI Assistant")

col_m1, col_m2 = st.columns([0.55, 0.45])
with col_m1:
    scope_mode = st.radio(
        "🔍 Inspection Scope:",
        ["Single Microflow Focus", "Workflow Chain Check", "Full Project Audit"],
        horizontal=True
    )
with col_m2:
    uploaded_files = st.file_uploader(
        "📎 Attach Files (Page .MPK, Screenshots, SCSS, XML)",
        type=["png", "jpg", "jpeg", "xml", "json", "txt", "mpk", "scss", "css"],
        accept_multiple_files=True,
        help="Pwede ka mag-upload og Page .MPK, Screenshot, o SCSS file dungan!"
    )

# Render Chat History with Live HTML Preview & Actions Toolbar
messages = get_session_messages(st.session_state.session_id)
for msg in messages:
    msg_id = msg["id"]
    role = msg["role"]
    content = msg["content"]
    
    with st.chat_message(role):
        st.markdown(content)
        
        # Auto-render Live HTML/UI Preview kung naay ```html block
        if role == "assistant" and "```html" in content:
            html_blocks = re.findall(r'```html(.*?)```', content, re.DOTALL)
            for idx, html_code in enumerate(html_blocks):
                st.caption(f"👁️ **Live Visual UI Preview #{idx+1}:**")
                components.html(html_code.strip(), height=230, scrolling=True)
        
        with st.expander("🛠️ Actions (Copy / Branch / Delete)", expanded=False):
            act_col1, act_col2, act_col3 = st.columns([0.25, 0.35, 0.4])
            
            with act_col1:
                if st.button("🗑️ Delete", key=f"del_msg_{msg_id}"):
                    delete_single_message(msg_id)
                    st.rerun()
                    
            with act_col2:
                if st.button("🔀 Branch from here", key=f"branch_{msg_id}"):
                    new_branch_id = str(uuid.uuid4())
                    branch_session_from_message(st.session_state.session_id, msg_id, new_branch_id)
                    st.session_state.session_id = new_branch_id
                    st.rerun()
                    
            with act_col3:
                st.code(content, language="markdown" if role == "assistant" else "text")

# 5. CHAT INPUT & EXECUTION
user_input = st.chat_input("Pangutana o ipasusi imong Mendix logic dinhi...")

if user_input:
    with st.chat_message("user"):
        st.markdown(user_input)
        if uploaded_files:
            file_names = [f.name for f in uploaded_files]
            st.caption(f"📎 Attached: {', '.join(file_names)}")
            
    add_message(st.session_state.session_id, "user", user_input, has_attachment=1 if uploaded_files else 0)
    
    attachment_data = parse_uploaded_files(uploaded_files) if uploaded_files else []
    
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
                
                # Check for Live HTML preview on the fresh response
                if "```html" in full_response:
                    html_blocks = re.findall(r'```html(.*?)```', full_response, re.DOTALL)
                    for idx, html_code in enumerate(html_blocks):
                        st.caption(f"👁️ **Live Visual UI Preview #{idx+1}:**")
                        components.html(html_code.strip(), height=230, scrolling=True)
                
                add_message(st.session_state.session_id, "assistant", full_response)
                st.rerun()
                
            except Exception as e:
                st.error(f"Error communicating with Gemini: {str(e)}")