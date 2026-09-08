import os
import streamlit as st
import streamlit.components.v1 as components
import uuid
import re
import sqlite3
from datetime import datetime
import config

# Dynamic Safe Importer
import core.chat_manager as cm

init_db = getattr(cm, "init_db")
create_session = getattr(cm, "create_session")
get_all_sessions = getattr(cm, "get_all_sessions")
get_session_messages = getattr(cm, "get_session_messages")
add_message = getattr(cm, "add_message")
delete_session = getattr(cm, "delete_session")
delete_single_message = getattr(cm, "delete_single_message")
branch_session_from_message = getattr(cm, "branch_session_from_message")
branch_session_with_summary = getattr(cm, "branch_session_with_summary")

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
            summary_text = f"🔄 **[SESSION TRANSFERRED FROM: '{old_title}']**\n\nThis conversation continues from the previous chat session. All context from uploaded Mendix files and guidelines remains active."
            cursor.execute(
                "INSERT INTO messages (session_id, role, content, has_attachment, created_at) VALUES (?, ?, ?, ?, ?)",
                (new_session_id, "assistant", summary_text, 1, datetime.now())
            )
            conn.commit()
        finally:
            conn.close()

from core.mendix_parser import (
    parse_uploaded_files, parse_uploaded_file, get_project_scss_context,
    scan_mendix_folder, generate_domain_model, compute_domain_model_signature,
    build_relevant_domain_context
)
from core.gemini_client import get_gemini_client, stream_chat_response, summarize_conversation_for_branch

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

# 3. Custom CSS (Restored Previous Working Header & Scrollbar)
st.markdown("""
<style>
/* Visible Scrollbar */
::-webkit-scrollbar {
    width: 8px !important;
    height: 8px !important;
}
::-webkit-scrollbar-track {
    background: #0f172a !important;
}
::-webkit-scrollbar-thumb {
    background: #334155 !important;
    border-radius: 4px !important;
}
::-webkit-scrollbar-thumb:hover {
    background: #0284c7 !important;
}

section.main {
    overflow-y: auto !important;
}

/* Sticky Top Controls with Divider and Blur Backdrop */
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
    padding-bottom: 95px !important;
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
</style>
""", unsafe_allow_html=True)

# 4. Session State Setup
def _set_active_session(new_id):
    """Sets the active chat AND mirrors it into the URL query params, so the
    correct chat can be restored even if the server-side session_state gets
    wiped (e.g. after a laptop sleep breaks the WebSocket connection and
    Streamlit silently starts a fresh session)."""
    st.session_state.session_id = new_id
    try:
        st.query_params["chat"] = new_id
    except Exception:
        pass  # very old Streamlit without query_params — chat still works, just won't survive a reconnect

if "session_id" not in st.session_state:
    _restored_id = None
    try:
        _candidate = st.query_params.get("chat")
        if _candidate and get_session_messages(_candidate):
            _restored_id = _candidate
    except Exception:
        _restored_id = None
    _set_active_session(_restored_id or str(uuid.uuid4()))

if "last_processed_ts" not in st.session_state:
    st.session_state.last_processed_ts = 0

if "session_parsed_files" not in st.session_state:
    st.session_state.session_parsed_files = {}

if "system_prompt" not in st.session_state:
    st.session_state.system_prompt = config.SYSTEM_PROMPT_PRESETS["🛡️ Senior Mendix Architect (Strict Best Practices & SOD)"]

if "domain_model_cache" not in st.session_state:
    # {signature, all_mermaid, summary, module_diagrams, modules_data, source}
    st.session_state.domain_model_cache = None

if "branch_toast" in st.session_state:
    st.toast(st.session_state.pop("branch_toast"), icon="🔀")

def ensure_domain_model_fresh(project_path, raw_mpk_files):
    """
    Cheap freshness check (mtime/name+size only — no reparsing) so the Domain
    Model is NOT reparsed on every AI request. Only reparses when there is no
    cache yet (and a source is available) or when the underlying source has
    actually changed since the last parse.
    """
    cache = st.session_state.get("domain_model_cache")
    current_sig = compute_domain_model_signature(project_path, raw_mpk_files)

    if current_sig is None:
        return cache

    if cache and cache.get("signature") == current_sig:
        return cache

    all_mermaid, summary, module_diagrams, modules_data, source = generate_domain_model(project_path, raw_mpk_files)
    if modules_data:
        new_cache = {
            "signature": current_sig,
            "all_mermaid": all_mermaid,
            "summary": summary,
            "module_diagrams": module_diagrams,
            "modules_data": modules_data,
            "source": source,
        }
        st.session_state.domain_model_cache = new_cache
        return new_cache

    return cache

# 🧬 Domain Model Diagram Modal (compact — never rendered inline in chat/page)
try:
    _dialog_decorator = st.dialog
except AttributeError:
    _dialog_decorator = getattr(st, "experimental_dialog", None)

def _make_domain_dialog_wrapper():
    """Tries to open the dialog at a larger width (newer Streamlit); falls
    back gracefully to the default width on older versions that don't
    support the 'width' kwarg."""
    if not _dialog_decorator:
        return None
    try:
        return _dialog_decorator("🧬 Domain Model Diagram", width="large")
    except TypeError:
        return _dialog_decorator("🧬 Domain Model Diagram")

_domain_dialog_wrapper = _make_domain_dialog_wrapper()

def _render_domain_model_diagram_body(cache):
    dm_summary = cache["summary"]
    all_mermaid = cache["all_mermaid"]
    module_diagrams = cache.get("module_diagrams", {})
    st.caption(dm_summary)

    with st.expander("ℹ️ Legend — reading the diagram", expanded=False):
        st.markdown(
            "**Entity color badge** (matches Studio Pro's blue/orange convention):\n\n"
            "- 🔵 = Persistent (stored in the database)\n"
            "- 🟠 = Non-persistent (transient — e.g. a REST/SOAP payload, calculation result, or notification object)\n"
            "- `(extends X)` next to the badge means this entity generalizes/inherits from entity `X`\n\n"
            "**Association lines** — Mendix only has **two** real association types "
            "(there's no separate '1-to-1' concept at the type level — a Reference "
            "*behaves* like one-to-one when a unique/validation rule constrains it, "
            "Mendix just doesn't store that as a distinct type):\n\n"
            "| Notation | Meaning | Mendix concept |\n"
            "|---|---|---|\n"
            "| `A \\|\\|--o{ B` | one (A) to zero-or-many (B) | **Reference** — the common case; B holds a reference to exactly one A |\n"
            "| `A }o--o{ B` | zero-or-many to zero-or-many | **ReferenceSet** — many-to-many |\n\n"
            "The label on the line is the association's real name from Studio Pro (e.g. `PurchaseRequest_Vendor`). "
            "A small stub box with a `Module_EntityName` label means that entity actually lives in a different module — "
            "shown here only because this association touches it."
        )

    available_mods = ["🌐 All Modules Combined"] + list(module_diagrams.keys())
    if len(available_mods) > 1:
        selected_mod_tab = st.radio(
            "Select Domain Model View:",
            available_mods,
            horizontal=True,
            key=f"dm_mod_selector_modal_{st.session_state.session_id}"
        )
        active_mermaid_code = all_mermaid if selected_mod_tab == "🌐 All Modules Combined" else module_diagrams.get(selected_mod_tab, all_mermaid)
    else:
        active_mermaid_code = all_mermaid

    mermaid_html = f"""
    <div id="m-wrap" style="background:#0f172a; padding:10px 14px; border-radius:8px; border:1px solid #334155; position:relative; margin:0;">
      <div style="position:absolute; top:8px; right:12px; z-index:100; display:flex; gap:6px;">
        <button onclick="window.zoomDiagram(1.15)" style="background:#0284c7; color:white; border:none; border-radius:4px; padding:4px 10px; font-size:12px; font-weight:bold; cursor:pointer;">🔍 Zoom (+)</button>
        <button onclick="window.zoomDiagram(0.87)" style="background:#334155; color:white; border:none; border-radius:4px; padding:4px 10px; font-size:12px; font-weight:bold; cursor:pointer;">🔍 Zoom (-)</button>
        <button onclick="window.fitToScreen()" style="background:#16a34a; color:white; border:none; border-radius:4px; padding:4px 10px; font-size:12px; font-weight:bold; cursor:pointer;">🧭 Fit to Screen</button>
        <button onclick="window.resetZoomFull()" style="background:#475569; color:white; border:none; border-radius:4px; padding:4px 10px; font-size:12px; font-weight:bold; cursor:pointer;">🔄 Reset (100%)</button>
      </div>
      <div id="mermaid-canvas-wrapper" style="overflow:auto; max-height:75vh; height:640px; padding:36px;">
        <pre class="mermaid" id="my-mermaid-diagram" style="display:inline-block; transform-origin:top left; transition:transform 0.15s; margin:0;">{active_mermaid_code}</pre>
      </div>
    </div>
    <script type="module">
      import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs';
      mermaid.initialize({{ startOnLoad: false, theme: 'dark', er: {{ useMaxWidth: false, fontSize: 15 }} }});

      let currentZoom = 1.0;

      function applyZoom() {{
        const elem = document.getElementById('my-mermaid-diagram');
        if (elem) elem.style.transform = `scale(${{currentZoom}})`;
      }}

      window.zoomDiagram = function(factor) {{
        currentZoom = Math.max(0.1, Math.min(currentZoom * factor, 5));
        applyZoom();
      }};

      window.resetZoomFull = function() {{
        currentZoom = 1.0;
        applyZoom();
      }};

      window.fitToScreen = function() {{
        const svg = document.querySelector('#my-mermaid-diagram svg');
        const wrapper = document.getElementById('mermaid-canvas-wrapper');
        if (!svg || !wrapper) return;
        let svgWidth, svgHeight;
        if (svg.viewBox && svg.viewBox.baseVal && svg.viewBox.baseVal.width) {{
          svgWidth = svg.viewBox.baseVal.width;
          svgHeight = svg.viewBox.baseVal.height;
        }} else {{
          const bbox = svg.getBBox();
          svgWidth = bbox.width;
          svgHeight = bbox.height;
        }}
        const availW = wrapper.clientWidth - 30;
        const availH = wrapper.clientHeight - 60;
        if (svgWidth > 0 && svgHeight > 0) {{
          currentZoom = Math.min(availW / svgWidth, availH / svgHeight);
          applyZoom();
        }}
      }};

      function autoResizeFrame() {{
        const h = document.getElementById('m-wrap').scrollHeight;
        window.parent.postMessage({{ isStreamlitMessage: true, type: "streamlit:setFrameHeight", height: Math.max(h + 8, 160) }}, "*");
      }}

      mermaid.run({{ querySelector: '.mermaid' }}).then(() => {{
        window.fitToScreen();
        autoResizeFrame();
        setTimeout(autoResizeFrame, 200);
      }});
    </script>
    """
    components.html(mermaid_html, height=700, scrolling=True)
    with st.expander("📄 View Raw Mermaid Code / Export", expanded=False):
        st.code(active_mermaid_code, language="mermaid")

if _domain_dialog_wrapper:
    @_domain_dialog_wrapper
    def domain_model_dialog():
        cache = st.session_state.get("domain_model_cache")
        if not cache or not cache.get("all_mermaid"):
            st.info("No Domain Model diagram has been generated yet.")
            return
        _render_domain_model_diagram_body(cache)
else:
    # Very old Streamlit fallback (no modal support): use a dismissible session flag.
    def domain_model_dialog():
        st.session_state.show_domain_model_fallback = True

# 5. SIDEBAR
with st.sidebar:
    st.title("⚡ Mendix Copilot")
    
    col_btn1, col_btn2 = st.columns([0.48, 0.52])
    with col_btn1:
        if st.button("➕ New", use_container_width=True, type="primary"):
            _set_active_session(str(uuid.uuid4()))
            st.rerun()
    with col_btn2:
        if st.button("⏩ Continue", help="Start a new chat carrying over context & files", use_container_width=True):
            new_id = str(uuid.uuid4())
            transfer_session_to_new(st.session_state.session_id, new_id)
            current_files = st.session_state.session_parsed_files.get(st.session_state.session_id, [])
            st.session_state.session_parsed_files[new_id] = current_files
            _set_active_session(new_id)
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
    st.caption(f"📊 ~{_approx_tokens:,} tokens estimate (this chat)")

    # Mendix Project Folder Input (Domain Model generation below prefers this path)
    st.subheader("📂 Mendix Project Path")
    project_path = st.text_input("Local Folder Path", placeholder="e.g. C:/MendixProjects/ProcureFlow")

    # 🧬 DOMAIN MODEL (Modules, Entities, Attributes & Associations)
    with st.expander("🧬 Domain Model", expanded=False):
        st.caption("The Local Project Path is preferred when configured and valid; otherwise, it uses the attached `.mpk` file(s).")

        _raw_attached_dm = st.session_state.get(f"uploader_{st.session_state.session_id}", [])
        if not isinstance(_raw_attached_dm, list):
            _raw_attached_dm = [_raw_attached_dm] if _raw_attached_dm else []

        dm_gen_col, dm_view_col = st.columns([0.55, 0.45])
        with dm_gen_col:
            if st.button("🧬 Generate Diagram", key="gen_domain_model_btn_sidebar", use_container_width=True):
                new_sig = compute_domain_model_signature(project_path, _raw_attached_dm)
                existing_cache = st.session_state.get("domain_model_cache")
                if existing_cache and existing_cache.get("signature") == new_sig:
                    st.info("♻️ No changes detected — using the existing Domain Model.")
                else:
                    with st.spinner("🧠 Parsing the Domain Model..."):
                        all_mermaid, summary, module_diagrams, modules_data, source = generate_domain_model(project_path, _raw_attached_dm)
                    if modules_data:
                        st.session_state.domain_model_cache = {
                            "signature": new_sig,
                            "all_mermaid": all_mermaid,
                            "summary": summary,
                            "module_diagrams": module_diagrams,
                            "modules_data": modules_data,
                            "source": source,
                        }
                        st.success("✅ Domain Model diagram generated!")
                    else:
                        # Persistent (not a fast-fading toast) so the reason is actually readable.
                        st.error(summary)

        _dm_cache = st.session_state.get("domain_model_cache")
        with dm_view_col:
            if _dm_cache and _dm_cache.get("all_mermaid"):
                if st.button("📊 View Diagram", key="view_domain_model_btn_sidebar", use_container_width=True):
                    if _dialog_decorator:
                        domain_model_dialog()
                    else:
                        st.session_state.show_domain_model_fallback = True
                        st.rerun()

        if _dm_cache and _dm_cache.get("summary"):
            st.caption(_dm_cache["summary"])

    st.divider()

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
    
    # Chat History List
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
            st.caption("No chats match your search.")
        
    for s_id, s_title, _ in sessions:
        col1, col2, col3 = st.columns([0.64, 0.18, 0.18])
        with col1:
            is_active = (s_id == st.session_state.session_id)
            label = f"👉 {s_title}" if is_active else f"📄 {s_title}"
            if st.button(label, key=f"btn_{s_id}", use_container_width=True, disabled=is_active):
                _set_active_session(s_id)
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
                        _set_active_session(str(uuid.uuid4()))
                    st.rerun()

# 6. STICKY TOP CONTROLS (Main Area - With Pinned Separator & Exact Spacing)
with st.container():
    st.markdown('<div class="sticky-header-marker"></div>', unsafe_allow_html=True)
    st.header("⚡ Mendix AI Assistant")

    col_m1, col_m2 = st.columns([0.45, 0.55])
    with col_m1:
        scope_mode = st.radio(
            "🔍 Inspection Scope:",
            ["Single Microflow Focus", "Workflow Chain Check", "Full Project Audit", "🎨 Page UI & SCSS Inspector"],
            key=f"scope_{st.session_state.session_id}",
            horizontal=True
        )
    with col_m2:
        uploaded_files = st.file_uploader(
            "📎 Attach Files (Page .MPK, Screenshots, .MD, SCSS, XML)",
            type=["png", "jpg", "jpeg", "xml", "json", "txt", "mpk", "scss", "css", "md"],
            accept_multiple_files=True,
            key=f"uploader_{st.session_state.session_id}",
            help="You can drag & drop multiple screenshots, .mpk packages, and scss files at once!"
        )

# 6b. Domain Model diagram intentionally NOT rendered here.
# Per product requirement it must never take up permanent chat/page space —
# it only opens on demand via the compact "📊 View Diagram" button in the
# sidebar's "🧬 Domain Model" expander, which pops the `domain_model_dialog()`
# modal defined near the top of this file.
if not _dialog_decorator and st.session_state.get("show_domain_model_fallback"):
    # Legacy Streamlit (<1.33) has no modal support at all — degrade gracefully
    # to a collapsible (collapsed-by-default) inline panel instead of a popup.
    _dm_cache_fallback = st.session_state.get("domain_model_cache")
    if _dm_cache_fallback and _dm_cache_fallback.get("all_mermaid"):
        with st.expander("🧬 Domain Model Diagram", expanded=True):
            if st.button("✖ Close", key="close_dm_fallback"):
                st.session_state.show_domain_model_fallback = False
                st.rerun()
            _render_domain_model_diagram_body(_dm_cache_fallback)

def render_live_preview(html_code, idx):
    """Dynamic Auto-Height Live Preview"""
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

                    with st.spinner("🧠 Summarizing this conversation so the new branch starts light but stays in context... (a few seconds)"):
                        history_upto = [m for m in get_session_messages(st.session_state.session_id) if m["id"] <= msg_id]
                        _branch_client = get_gemini_client()
                        summary_text = summarize_conversation_for_branch(_branch_client, model_choice, history_upto)

                    branch_session_with_summary(st.session_state.session_id, msg_id, new_branch_id, summary_text)

                    # Carry over parsed attachment content (same mechanism the "Continue" button uses —
                    # file_uploader widgets can't be programmatically populated, but their already-extracted
                    # content can be handed straight to the new session).
                    current_files = st.session_state.session_parsed_files.get(st.session_state.session_id, [])
                    st.session_state.session_parsed_files[new_branch_id] = current_files

                    # Carry over Inspection Scope (this widget's key is session-scoped, so pre-seed the new
                    # session's key before its radio is first instantiated).
                    st.session_state[f"scope_{new_branch_id}"] = st.session_state.get(
                        f"scope_{st.session_state.session_id}", "Single Microflow Focus"
                    )

                    _set_active_session(new_branch_id)
                    st.session_state.branch_toast = "🔀 Branched with a fresh summary — settings & files carried over!"
                    st.rerun()

needs_resume = (len(messages) > 0 and messages[-1]["role"] == "user")
if needs_resume:
    st.warning("⚠️ The previous AI response in this chat was interrupted.")
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
    scss_context = ""
    if project_path:
        context_info += f"Mendix Local Project Path: {project_path}\n"
        scss_context = get_project_scss_context(project_path)
        if scss_context:
            context_info += scss_context
        if scope_mode == "Full Project Audit":
            context_info += "\n" + scan_mendix_folder(project_path)

    # 🧬 Domain Model context for the AI (indexed/cached — reparsed only if the
    # underlying .mpr/.mpk source actually changed, never on every request).
    _raw_attached_for_dm = st.session_state.get(f"uploader_{st.session_state.session_id}", [])
    if not isinstance(_raw_attached_for_dm, list):
        _raw_attached_for_dm = [_raw_attached_for_dm] if _raw_attached_for_dm else []
    dm_cache = ensure_domain_model_fresh(project_path, _raw_attached_for_dm)

    if scope_mode == "🎨 Page UI & SCSS Inspector" and dm_cache and dm_cache.get("modules_data"):
        page_reference_text = scss_context
        for item in attachment_data:
            if item.get("type") == "text":
                page_reference_text += "\n" + item.get("data", "")
        domain_ctx = build_relevant_domain_context(dm_cache["modules_data"], page_reference_text)
        if domain_ctx:
            context_info += "\n\n" + domain_ctx

    client = get_gemini_client()
    if not client:
        st.error("⚠️ Please check your GEMINI_API_KEY in the `.env` file!")
    else:
        with st.chat_message("assistant"):
            current_messages = [
                {"role": m["role"], "content": m["content"]}
                for m in get_session_messages(st.session_state.session_id)
            ]
            
            with st.status(f"🧠 Mendix Copilot ({model_choice}) is analyzing & generating...", expanded=True) as status_box:
                response_placeholder = st.empty()
                full_response = ""
                last_model_idx = 0
                
                def handle_fallback(old_m, new_m):
                    status_box.write(f"⚠️ *Notice: `{old_m}` is busy/503. Automatically switching to fallback: `{new_m}`...*")
                
                try:
                    for chunk_obj in stream_chat_response(
                        client=client,
                        model_name=model_choice,
                        messages_history=current_messages,
                        system_instruction=st.session_state.system_prompt,
                        attachments=attachment_data,
                        context_info=context_info,
                        on_fallback_callback=handle_fallback
                    ):
                        if chunk_obj.get("is_fresh_model", False) and chunk_obj.get("model_idx", 0) > last_model_idx:
                            full_response = ""
                            last_model_idx = chunk_obj["model_idx"]
                            
                        chunk_text = chunk_obj["text"]
                        full_response += chunk_text
                        
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