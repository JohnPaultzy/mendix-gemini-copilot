import os
import zipfile
import io
import re
from PIL import Image

def extract_page_structure_from_text(raw_text):
    """Mopili sa mga importanteng Mendix Page Elements gikan sa extracted MPK text."""
    containers = set(re.findall(r'\b(container[A-Za-z0-9_]*|layoutGrid[A-Za-z0-9_]*|dataView[A-Za-z0-9_]*|card[A-Za-z0-9_]*)\b', raw_text, re.IGNORECASE))
    classes = set(re.findall(r'class="([^"]+)"', raw_text))
    design_props = set(re.findall(r'designProperties="([^"]+)"', raw_text))
    
    summary = []
    summary.append("📑 PARSED MENDIX PAGE STRUCTURE & WIDGETS:")
    if containers:
        summary.append(f"• Detected Containers/Wrappers: {', '.join(list(containers)[:30])}")
    if classes:
        summary.append(f"• Existing Classes: {', '.join(list(classes)[:20])}")
    if design_props:
        summary.append(f"• Design Properties: {', '.join(list(design_props)[:20])}")
        
    return "\n".join(summary)

def parse_uploaded_files(uploaded_files):
    """Basa sa daghang gi-upload nga Page .MPK, Images, o SCSS files."""
    if not uploaded_files:
        return []
    
    # Handle single file passed as not a list
    if not isinstance(uploaded_files, list):
        uploaded_files = [uploaded_files]
        
    parsed_items = []
    
    for f in uploaded_files:
        if f is None:
            continue
            
        file_name = f.name.lower()
        
        # 1. Screenshot Image
        if f.type and "image" in f.type:
            image = Image.open(f)
            parsed_items.append({"type": "image", "data": image, "name": f.name})
            
        # 2. Page / Microflow .MPK Package
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
                
        # 3. Text / SCSS / CSS / XML / JSON
        else:
            try:
                content = f.read().decode("utf-8", errors="ignore")
                parsed_items.append({"type": "text", "data": f"--- UPLOADED FILE: {f.name} ---\n{content}", "name": f.name})
            except Exception as e:
                parsed_items.append({"type": "text", "data": f"Error reading {f.name}: {e}", "name": f.name})
                
    return parsed_items

# Alias para mosugot bisan 'parse_uploaded_file' ang tawag sa app.py
def parse_uploaded_file(uploaded_file):
    return parse_uploaded_files(uploaded_file)

def get_project_scss_context(project_path):
    """Diretsong mobasa sa tanang SCSS files gikan sa theme/web/ folder sa Project Path."""
    if not project_path or not os.path.exists(project_path):
        return ""
    
    theme_web_dir = os.path.join(project_path, "theme", "web")
    if not os.path.exists(theme_web_dir):
        return f"\n⚠️ Note: No theme/web folder found at {project_path}"
    
    scss_dump = []
    scss_dump.append(f"\n=======================================================")
    scss_dump.append(f"🎨 LOCAL THEME SCSS FILES DETECTED (Path: {theme_web_dir})")
    scss_dump.append(f"=======================================================")
    
    for root, dirs, files in os.walk(theme_web_dir):
        for file in files:
            if file.endswith((".scss", ".css")):
                full_file_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_file_path, project_path)
                try:
                    with open(full_file_path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                        scss_dump.append(f"\n--- SCSS FILE: {rel_path} (Full Path: {full_file_path}) ---")
                        scss_dump.append(content[:15000])
                except Exception as e:
                    scss_dump.append(f"\nCould not read {rel_path}: {e}")
                    
    return "\n".join(scss_dump)

def scan_mendix_folder(folder_path):
    """Mobiyahe sa tibuok Mendix folder para sa Full Project Audit."""
    if not folder_path or not os.path.exists(folder_path):
        return "Project folder not found or path is empty."
    
    summary = [f"📁 MENDIX PROJECT ROOT: {folder_path}\n"]
    
    for root, dirs, files in os.walk(folder_path):
        for file in files:
            if file.endswith((".mpr", ".xml", ".json", ".java", ".scss", ".css")):
                rel_path = os.path.relpath(os.path.join(root, file), folder_path)
                summary.append(f" - {rel_path}")
                
    return "\n".join(summary[:100])