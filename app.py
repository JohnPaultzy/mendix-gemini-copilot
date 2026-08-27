import streamlit as st
import streamlit.components.v1 as components
import uuid
import re
import json
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

# 2. Custom CSS
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
</style>
""", unsafe_allow_html=True)

# 3. Session State Setup
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())
    create_session(st.session_state.session_id, "New Chat")

if "system_prompt" not in st.session_state:
    st.session_state.system_prompt = config.SYSTEM_PROMPT_PRESETS["🛡️ Senior Mendix Architect (Strict Best Practices & SOD)"]

if "branch_toast" in st.session_state:
    st.toast(st.session_state.pop("branch_toast"), icon="🔀")

# 4. SIDEBAR
with st.sidebar:
    st.title("⚡ Mendix Copilot")
    
    if st.button("➕ New Chat", use_container_width=True, type="primary"):
        new_id = str(uuid.uuid4())
        st.session_state.session_id = new_id
        create_session(new_id, "New Chat", st.session_state.system_prompt)
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
    
    # Chat History List
    st.subheader("💬 Chat History")
    sessions = get_all_sessions()
    
    session_ids = [s[0] for s in sessions]
    if st.session_state.session_id not in session_ids:
        create_session(st.session_state.session_id, "New Chat", st.session_state.system_prompt)
        sessions = get_all_sessions()
        
    for s_id, s_title, _ in sessions:
        col1, col2 = st.columns([0.78, 0.22])
        with col1:
            is_active = (s_id == st.session_state.session_id)
            label = f"👉 {s_title}" if is_active else f"📄 {s_title}"
            if st.button(label, key=f"btn_{s_id}", use_container_width=True):
                st.session_state.session_id = s_id
                st.rerun()
        with col2:
            with st.popover("🗑️", help="Delete Chat"):
                st.write("**Delete chat?**")
                if st.button("Confirm Delete", key=f"confirm_del_{s_id}", type="primary", use_container_width=True):
                    delete_session(s_id)
                    if st.session_state.session_id == s_id:
                        new_session_id = str(uuid.uuid4())
                        st.session_state.session_id = new_session_id
                        create_session(new_session_id, "New Chat", st.session_state.system_prompt)
                    st.rerun()

# 5. STICKY TOP CONTROLS (Main Area)
with st.container():
    st.markdown('<div class="sticky-header-marker"></div>', unsafe_allow_html=True)
    st.header("⚡ Mendix AI Assistant")

    col_m1, col_m2 = st.columns([0.5, 0.5])
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
            help="Pwede ka mag-upload og Page .MPK, Screenshots, .MD rules, o SCSS file dungan!"
        )

# 6. RENDER CHAT MESSAGES
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

# 7. INTERACTIVE MULTI-IMAGE CLIPBOARD STAGING & REMOVAL GALLERY
multi_paste_gallery_js = """
<div id="staging-box" style="display:none; background:#1e293b; border:1px solid #334155; border-radius:8px; padding:10px 14px; margin-bottom:8px;">
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
        <span style="font-size:12px; color:#cbd5e1; font-weight:600;">
            📸 Attached Screenshots (<span id="staged-count">0</span>) - <span style="color:#94a3b8; font-weight:normal;">Press Ctrl+V to add more</span>
        </span>
        <button onclick="clearAllStagedImages()" style="background:#ef4444; border:none; color:white; font-size:11px; padding:3px 8px; border-radius:4px; cursor:pointer; font-weight:bold;">
            Clear All 🗑️
        </button>
    </div>
    <div id="thumbnails-wrapper" style="display:flex; gap:10px; flex-wrap:wrap;"></div>
</div>

<script>
window.stagedPastedImages = window.stagedPastedImages || [];

function renderThumbnails() {
    const stagingBox = document.getElementById('staging-box');
    const wrapper = document.getElementById('thumbnails-wrapper');
    const countSpan = document.getElementById('staged-count');
    const chatTextarea = window.parent.document.querySelector('textarea[data-testid="stChatInputTextArea"]');

    if (!wrapper || !stagingBox) return;

    if (window.stagedPastedImages.length === 0) {
        stagingBox.style.display = 'none';
        if (chatTextarea && chatTextarea.value.startsWith('📸 [')) {
            chatTextarea.value = chatTextarea.value.replace(/^📸 \[[0-9]+ Screenshot\(s\) Attached\]\s*/, '');
        }
        return;
    }

    stagingBox.style.display = 'block';
    countSpan.innerText = window.stagedPastedImages.length;
    wrapper.innerHTML = '';

    window.stagedPastedImages.forEach((imgB64, index) => {
        const thumbDiv = document.createElement('div');
        thumbDiv.style.cssText = 'position:relative; width:64px; height:64px; border-radius:6px; overflow:hidden; border:2px solid #475569; background:#0f172a;';

        const img = document.createElement('img');
        img.src = imgB64;
        img.style.cssText = 'width:100%; height:100%; object-fit:cover;';

        const delBtn = document.createElement('button');
        delBtn.innerHTML = '✕';
        delBtn.title = 'Remove this image';
        delBtn.style.cssText = 'position:absolute; top:2px; right:2px; background:rgba(239,68,68,0.85); color:white; border:none; border-radius:50%; width:18px; height:18px; font-size:11px; cursor:pointer; display:flex; align-items:center; justify-content:center; line-height:1; font-weight:bold;';
        delBtn.onclick = function(e) {
            e.stopPropagation();
            removeSingleImage(index);
        };

        thumbDiv.appendChild(img);
        thumbDiv.appendChild(delBtn);
        wrapper.appendChild(thumbDiv);
    });

    // Update prefix sa chat input
    if (chatTextarea) {
        const prefix = `📸 [${window.stagedPastedImages.length} Screenshot(s) Attached] `;
        if (!chatTextarea.value.startsWith('📸 [')) {
            chatTextarea.value = prefix + chatTextarea.value;
        } else {
            chatTextarea.value = chatTextarea.value.replace(/^📸 \[[0-9]+ Screenshot\(s\) Attached\]\s*/, prefix);
        }
    }
}

function removeSingleImage(index) {
    window.stagedPastedImages.splice(index, 1);
    renderThumbnails();
}

function clearAllStagedImages() {
    window.stagedPastedImages = [];
    renderThumbnails();
}

function attachPasteHook() {
    const chatTextarea = window.parent.document.querySelector('textarea[data-testid="stChatInputTextArea"]');
    if (!chatTextarea || chatTextarea.getAttribute('data-gallery-paste-hooked')) return;

    chatTextarea.setAttribute('data-gallery-paste-hooked', 'true');
    
    window.parent.document.addEventListener('paste', function(e) {
        const items = (e.clipboardData || window.clipboardData).items;
        let added = false;
        for (let i = 0; i < items.length; i++) {
            if (items[i].type.indexOf('image') !== -1) {
                const blob = items[i].getAsFile();
                const reader = new FileReader();
                reader.onload = function(event) {
                    window.stagedPastedImages.push(event.target.result);
                    renderThumbnails();
                };
                reader.readAsDataURL(blob);
                added = true;
            }
        }
    });
}

setInterval(attachPasteHook, 500);
</script>
"""
components.html(multi_paste_gallery_js, height=105)

# 8. CHAT INPUT & EXECUTION
user_input = st.chat_input("Pangutana o i-Ctrl+V ang screenshots direkta dinhi...")

if user_input:
    # Check kung naay pasted images count sa prefix
    pasted_count = 0
    match = re.search(r'📸 \[([0-9]+) Screenshot\(s\) Attached\]', user_input)
    if match:
        pasted_count = int(match.group(1))
        clean_user_input = re.sub(r'📸 \[[0-9]+ Screenshot\(s\) Attached\]\s*', '', user_input)
    else:
        clean_user_input = user_input
        
    attached_names = []
    if uploaded_files:
        attached_names.extend([f.name for f in uploaded_files])
    if md_guideline:
        attached_names.append(f"Guideline: {md_guideline.name}")
    if pasted_count > 0:
        attached_names.append(f"{pasted_count} Pasted Screenshot(s)")
        
    final_user_content = clean_user_input if clean_user_input.strip() else "(Attached Images/Files)"
    if attached_names:
        final_user_content += f"\n\n<div class='attached-badge'>📎 Attached: {', '.join(attached_names)}</div>"

    with st.chat_message("user"):
        st.markdown(final_user_content, unsafe_allow_html=True)
            
    add_message(st.session_state.session_id, "user", final_user_content, has_attachment=1 if attached_names else 0)
    
    # Process files
    all_files_to_parse = list(uploaded_files) if uploaded_files else []
    if md_guideline:
        all_files_to_parse.append(md_guideline)
        
    attachment_data = parse_uploaded_files(all_files_to_parse)
    
    # Context Preparation
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