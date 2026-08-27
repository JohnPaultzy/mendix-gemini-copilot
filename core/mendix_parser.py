import os
import zipfile
import io
import re
import base64
import json
from PIL import Image

def extract_page_structure_from_text(raw_text):
    containers = set(re.findall(r'\b(container[A-Za-z0-9_]*|layoutGrid[A-Za-z0-9_]*|dataView[A-Za-z0-9_]*|card[A-Za-z0-9_]*)\b', raw_text, re.IGNORECASE))
    classes = set(re.findall(r'class="([^"]+)"', raw_text))
    design_props = set(re.findall(r'designProperties="([^"]+)"', raw_text))
    
    summary = ["📑 PARSED MENDIX PAGE STRUCTURE & WIDGETS:"]
    if containers:
        summary.append(f"• Detected Containers/Wrappers: {', '.join(list(containers)[:30])}")
    if classes:
        summary.append(f"• Existing Classes: {', '.join(list(classes)[:20])}")
    if design_props:
        summary.append(f"• Design Properties: {', '.join(list(design_props)[:20])}")
        
    return "\n".join(summary)

def parse_uploaded_files(uploaded_files, pasted_images_b64=None):
    """Basa sa tanang gi-upload nga files lakip ang Pasted Base64 Images."""
    parsed_items = []
    
    # 1. Process Pasted Base64 Images gikan sa Custom Chatbox
    if pasted_images_b64:
        if isinstance(pasted_images_b64, str):
            try:
                pasted_images_b64 = json.loads(pasted_images_b64)
            except Exception:
                pasted_images_b64 = [pasted_images_b64]
                
        for idx, b64_str in enumerate(pasted_images_b64):
            if b64_str:
                try:
                    if "," in b64_str:
                        b64_str = b64_str.split(",")[1]
                    img_bytes = base64.b64decode(b64_str)
                    img = Image.open(io.BytesIO(img_bytes))
                    parsed_items.append({
                        "type": "image", 
                        "data": img, 
                        "name": f"Pasted_Screenshot_{idx+1}.png"
                    })
                except Exception as e:
                    parsed_items.append({"type": "text", "data": f"Error loading pasted image {idx+1}: {e}", "name": "Clipboard_Error"})

    if not uploaded_files:
        return parsed_items
    
    if not isinstance(uploaded_files, list):
        uploaded_files = [uploaded_files]
    
    for f in uploaded_files:
        if f is None:
            continue
            
        file_name = f.name.lower()
        
        # 2. Screenshot Image file upload
        if f.type and "image" in f.type:
            image = Image.open(f)
            parsed_items.append({"type": "image", "data": image, "name": f.name})
            
        # 3. .MD Reference Document
        elif file_name.endswith(".md"):
            try:
                content = f.read().decode("utf-8", errors="ignore")
                parsed_items.append({
                    "type": "text", 
                    "data": f"📖 [ACTIVE REFERENCE / PROJECT GUIDELINE DOCUMENT ({f.name})]:\n\n{content}", 
                    "name": f.name
                })
            except Exception as e:
                parsed_items.append({"type": "text", "data": f"Error reading .md reference: {e}", "name": f.name})
                
        # 4. .MPK Package
        elif file_name.endswith(".mpk"):
            try:
                zip_buffer = io.BytesIO(f.read())
                extracted = [f"📦 UPLOADED PACKAGE (.MPK): {f.name}\n"]
                raw_combined = []
                
                with zipfile.ZipFile(zip_buffer, 'r') as zip_ref:
                    for info in zip_ref.infolist():
                        if not info.is_dir() and not info.filename.endswith(('.png', '.jpg', '.jpeg', '.jar')):
                            try:
                                with zip_ref.open(info) as sub_f:
                                    content = sub_f.read().decode('utf-8', errors='ignore')
                                    raw_combined.append(content)
                                    extracted.append(f"--- FILE INSIDE MPK: {info.filename} ---")
                                    extracted.append(content[:30000])
                            except Exception:
                                continue
                                
                full_text = "\n".join(raw_combined)
                page_analysis = extract_page_structure_from_text(full_text)
                extracted.insert(1, page_analysis + "\n------------------------------------------\n")
                
                parsed_items.append({"type": "text", "data": "\n\n".join(extracted), "name": f.name})
            except Exception as e:
                parsed_items.append({"type": "text", "data": f"Error parsing .mpk: {e}", "name": f.name})
                
        # 5. Text / SCSS / CSS
        else:
            try:
                content = f.read().decode("utf-8", errors="ignore")
                parsed_items.append({"type": "text", "data": f"--- UPLOADED FILE: {f.name} ---\n{content}", "name": f.name})
            except Exception as e:
                parsed_items.append({"type": "text", "data": f"Error reading {f.name}: {e}", "name": f.name})
                
    return parsed_items

def parse_uploaded_file(uploaded_file):
    return parse_uploaded_files(uploaded_file)

def get_project_scss_context(project_path):
    if not project_path or not os.path.exists(project_path):
        return ""
    
    theme_web_dir = os.path.join(project_path, "theme", "web")
    if not os.path.exists(theme_web_dir):
        return ""
    
    scss_dump = [f"\n🎨 LOCAL THEME SCSS FILES (Path: {theme_web_dir})\n"]
    for root, dirs, files in os.walk(theme_web_dir):
        for file in files:
            if file.endswith((".scss", ".css")):
                full_file_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_file_path, project_path)
                try:
                    with open(full_file_path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                        scss_dump.append(f"\n--- SCSS FILE: {rel_path} ---")
                        scss_dump.append(content[:15000])
                except Exception:
                    continue
                    
    return "\n".join(scss_dump)

def scan_mendix_folder(folder_path):
    if not folder_path or not os.path.exists(folder_path):
        return ""
    summary = [f"📁 MENDIX PROJECT ROOT: {folder_path}\n"]
    for root, dirs, files in os.walk(folder_path):
        for file in files:
            if file.endswith((".mpr", ".xml", ".json", ".java", ".scss", ".css", ".md")):
                rel_path = os.path.relpath(os.path.join(root, file), folder_path)
                summary.append(f" - {rel_path}")
    return "\n".join(summary[:100])