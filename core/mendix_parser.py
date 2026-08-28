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
        
        if f.type and "image" in f.type:
            image = Image.open(f)
            parsed_items.append({"type": "image", "data": image, "name": f.name})
            
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
                
        elif file_name.endswith(".mpk"):
            try:
                f.seek(0)
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


def extract_domain_model_mermaid(uploaded_files):
    """
    Best-effort nga pag-parse sa Entities/Associations gikan sa .mpk package(s)
    aron mahimo nga Mermaid erDiagram string.

    IMPORTANTE: Walay official public schema para sa Mendix domain-model XML,
    mao nga kini nga parser gamit ra regex sa mga common nga pattern (Entity /
    Association tags) nga makit-an sa extracted XML files sulod sa .mpk.
    Puede dili 100% kompleto sa tanang Mendix version, pero maghatag og
    maayong starting point/preview sa entity relationships.
    """
    if not uploaded_files:
        return None, "Walay na-upload nga .mpk file para ma-scan."

    if not isinstance(uploaded_files, list):
        uploaded_files = [uploaded_files]

    entities = set()
    associations = []  # (parent_short, child_short, assoc_name)

    entity_pattern = re.compile(r'<Entities\.Entity[^>]*Name="([A-Za-z0-9_]+)"', re.IGNORECASE)
    entity_pattern_alt = re.compile(r'<Entity[^>]*[Nn]ame="([A-Za-z0-9_]+)"')
    assoc_pattern = re.compile(
        r'<Entities\.Association[^>]*Name="([A-Za-z0-9_]+)"[^>]*?Parent="([A-Za-z0-9_.]+)"[^>]*?Child="([A-Za-z0-9_.]+)"',
        re.IGNORECASE | re.DOTALL
    )

    found_any_mpk = False

    for f in uploaded_files:
        if f is None:
            continue
        file_name = f.name.lower()
        if not file_name.endswith(".mpk"):
            continue
        found_any_mpk = True
        try:
            f.seek(0)
            zip_buffer = io.BytesIO(f.read())
            with zipfile.ZipFile(zip_buffer, 'r') as zip_ref:
                for info in zip_ref.infolist():
                    if info.is_dir():
                        continue
                    if info.filename.endswith(('.png', '.jpg', '.jpeg', '.jar')):
                        continue
                    try:
                        with zip_ref.open(info) as sub_f:
                            content = sub_f.read().decode('utf-8', errors='ignore')
                    except Exception:
                        continue

                    for m in entity_pattern.finditer(content):
                        entities.add(m.group(1))
                    for m in entity_pattern_alt.finditer(content):
                        entities.add(m.group(1))
                    for m in assoc_pattern.finditer(content):
                        assoc_name, parent, child = m.group(1), m.group(2), m.group(3)
                        parent_short = parent.split(".")[-1]
                        child_short = child.split(".")[-1]
                        associations.append((parent_short, child_short, assoc_name))
                        entities.add(parent_short)
                        entities.add(child_short)
        except Exception:
            continue

    if not found_any_mpk:
        return None, "Walay .mpk file nga na-detect sa imong gi-attach. I-attach usa ka .mpk aron ma-generate ang diagram."

    if not entities:
        return None, "Na-scan ang .mpk pero walay entity pattern nga nakit-an. Posible lahi ang XML structure niini nga Mendix version, o dili domain model ang naa sa sulod niini nga package."

    lines = ["erDiagram"]
    for parent, child, name in associations:
        safe_name = re.sub(r'[^A-Za-z0-9_]', '_', name) or "relates_to"
        lines.append(f'    {parent} ||--o{{ {child} : "{safe_name}"')

    linked_entities = {e for pair in associations for e in pair[:2]}
    orphan_entities = entities - linked_entities
    for e in sorted(orphan_entities):
        lines.append(f"    {e}")

    mermaid_code = "\n".join(lines)
    summary = f"✅ {len(entities)} entities ug {len(associations)} associations ang nakit-an."
    return mermaid_code, summary