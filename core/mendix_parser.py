import os
import zipfile
import io
import re
import base64
import json
import uuid
import zlib
import sqlite3
import struct
import xml.etree.ElementTree as ET
from PIL import Image

def parse_deep_page_hierarchy(xml_content):
    try:
        root = ET.fromstring(xml_content)
    except Exception:
        return ""

    hierarchy_lines = [
        "=================================================================",
        "📑 COMPLETE MENDIX PAGE & WIDGET ARCHITECTURE (OMNI-PARSED)",
        "================================================================="
    ]

    def clean_tag(tag):
        return tag.split('}')[-1] if '}' in tag else tag

    def extract_common_meta(attrs):
        meta = []
        name = attrs.get("Name", "")
        css_class = attrs.get("Class", "")
        design_props = attrs.get("DesignProperties", "")
        style = attrs.get("Style", "")
        visibility = attrs.get("ConditionalVisibility", attrs.get("Visibility", ""))
        
        if name: meta.append(f'id: .mx-name-{name}')
        if css_class: meta.append(f'class: "{css_class}"')
        if design_props: meta.append(f'designProps: "{design_props}"')
        if style: meta.append(f'style: "{style}"')
        if visibility: meta.append(f'visibleIf: [{visibility}]')
        return " | ".join(meta)

    def traverse(node, depth=0):
        indent = "  " * depth
        tag = clean_tag(node.tag)
        attrs = node.attrib
        meta_str = extract_common_meta(attrs)
        meta_formatted = f" ({meta_str})" if meta_str else ""

        if "LayoutGrid" in tag and "Row" not in tag and "Column" not in tag:
            hierarchy_lines.append(f"{indent}📐 [LayoutGrid]{meta_formatted}")
        elif "LayoutGridRow" in tag:
            hierarchy_lines.append(f"{indent}  ├── [Row]")
        elif "LayoutGridColumn" in tag:
            weight = attrs.get("Weight", attrs.get("Span", "Auto"))
            hierarchy_lines.append(f"{indent}      └── [Column (Span/Weight: {weight})]{meta_formatted}")
        elif "MasterLayout" in tag or "Layout" in tag:
            hierarchy_lines.append(f"{indent}🏛️ [MasterLayout: {attrs.get('Name', tag)}]{meta_formatted}")
        elif any(k in tag for k in ["Container", "Div", "GroupBox", "TabContainer", "TabPane", "ScrollContainer"]):
            hierarchy_lines.append(f"{indent}📁 [{tag}]{meta_formatted}")
        elif any(k in tag for k in ["DataView", "DataGrid", "DataGrid2", "ListView", "Gallery", "TemplateGrid"]):
            entity = attrs.get("Entity", attrs.get("DataSource", attrs.get("EntityPath", "Context Object")))
            ds_type = attrs.get("DataSourceType", "")
            ds_str = f" [Entity: {entity}{', Type: ' + ds_type if ds_type else ''}]"
            hierarchy_lines.append(f"{indent}📦 [{tag}]{ds_str}{meta_formatted}")
        elif any(k in tag for k in ["TextBox", "TextArea", "DropDown", "DatePicker", "CheckBox", "RadioButtons", "Switch", "ReferenceSelector", "InputMask"]):
            attr_bind = attrs.get("Attribute", attrs.get("DataSource", ""))
            label = attrs.get("LabelCaption", attrs.get("Caption", ""))
            on_change = attrs.get("OnChangeAction", attrs.get("OnChangeMicroflow", attrs.get("OnChangeNanoflow", "")))
            details = []
            if label: details.append(f'Label: "{label}"')
            if attr_bind: details.append(f'Binds: ${attr_bind}')
            if on_change: details.append(f'⚡ OnChange: {on_change}')
            detail_str = f" [{', '.join(details)}]" if details else ""
            hierarchy_lines.append(f"{indent}✏️ [{tag}]{detail_str}{meta_formatted}")
        elif any(k in tag for k in ["ActionButton", "Button", "CallMicroflowButton", "CallNanoflowButton", "OpenPageButton", "SaveButton", "CancelButton", "ClosePageButton", "Link"]):
            caption = attrs.get("Caption", attrs.get("Title", "Button"))
            on_click = attrs.get("OnClickAction", attrs.get("OnClickMicroflow", attrs.get("OnClickNanoflow", "")))
            icon = attrs.get("Icon", attrs.get("ButtonIcon", ""))
            details = [f'Caption: "{caption}"']
            if on_click: details.append(f'⚡ OnClick: {on_click}')
            if icon: details.append(f'Icon: {icon}')
            hierarchy_lines.append(f"{indent}🔘 [{tag}] [{', '.join(details)}]{meta_formatted}")
        elif any(k in tag for k in ["MenuBar", "Menu", "NavigationTree", "NavigationList", "Sidebar", "Breadcrumbs", "MenuItem"]):
            caption = attrs.get("Caption", attrs.get("Name", tag))
            action = attrs.get("Action", attrs.get("Page", ""))
            action_str = f" -> {action}" if action else ""
            hierarchy_lines.append(f"{indent}🧭 [Nav: {tag} \"{caption}\"{action_str}]{meta_formatted}")
        elif any(k in tag for k in ["StaticText", "DynamicText", "Label", "Badge", "Image", "Icon", "ProgressBar", "Alert"]):
            caption = attrs.get("Caption", attrs.get("Text", attrs.get("Value", "")))
            cap_str = f' "{caption}"' if caption else ""
            hierarchy_lines.append(f"{indent}🏷️ [{tag}{cap_str}]{meta_formatted}")
        elif any(k in tag for k in ["Chart", "TimeSeries", "BarChart", "PieChart", "CustomWidget", "Widget", "PluggableWidget"]):
            w_id = attrs.get("WidgetId", attrs.get("Type", attrs.get("Id", "CustomWidget")))
            hierarchy_lines.append(f"{indent}🧩 [CustomWidget/AddOn: {w_id}]{meta_formatted}")
        elif len(tag) > 2 and not tag.startswith("_"):
            hierarchy_lines.append(f"{indent}🔹 [{tag}]{meta_formatted}")

        for child in node:
            traverse(child, depth + 1)

    traverse(root)
    return "\n".join(hierarchy_lines)

def parse_uploaded_files(uploaded_files, pasted_images_b64=None):
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
                extracted = [f"📦 UPLOADED MENDIX PACKAGE (.MPK): {f.name}\n"]
                raw_combined = []
                deep_page_hierarchies = []
                
                with zipfile.ZipFile(zip_buffer, 'r') as zip_ref:
                    for info in zip_ref.infolist():
                        if not info.is_dir() and not info.filename.endswith(('.png', '.jpg', '.jpeg', '.jar')):
                            try:
                                with zip_ref.open(info) as sub_f:
                                    content = sub_f.read().decode('utf-8', errors='ignore')
                                    raw_combined.append(content)
                                    
                                    if any(k in content for k in ["<Form", "<LayoutGrid", "<Container", "<DataView", "<Page"]):
                                        page_tree = parse_deep_page_hierarchy(content)
                                        if page_tree:
                                            deep_page_hierarchies.append(f"📄 Full Architecture of '{info.filename}':\n" + page_tree)
                                            
                                    extracted.append(f"--- FILE INSIDE MPK: {info.filename} ---")
                                    extracted.append(content[:30000])
                            except Exception:
                                continue
                                
                if deep_page_hierarchies:
                    extracted.insert(1, "\n\n".join(deep_page_hierarchies) + "\n------------------------------------------\n")
                
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

def extract_all_strings_from_blob(byte_data):
    """Mendix 10 SQLite Multi-Offset Zlib Chunk Decompressor."""
    strings = []
    for offset in [0, 4, 8, 12, 16, 20]:
        try:
            decomp = zlib.decompress(byte_data[offset:])
            for m in re.finditer(rb'[\x20-\x7E]{2,}', decomp):
                strings.append(m.group(0).decode('utf-8', errors='ignore'))
        except Exception:
            pass

    for m in re.finditer(rb'[\x20-\x7E]{2,}', byte_data):
        strings.append(m.group(0).decode('utf-8', errors='ignore'))

    return strings

# ---------------------------------------------------------------------------
# BSON decoder for Mendix .mxunit files (newer Git-friendly project storage).
# Newer Mendix Studio Pro projects ("Use Git" / split-.mpr format) store the
# .mpr as a lightweight tree index (Unit table: UnitID/ContainerID/
# ContainmentName) while the actual unit content lives externally in
# mprcontents/<guid[0:2]>/<guid[2:4]>/<guid>.mxunit as raw BSON documents.
# ---------------------------------------------------------------------------

def _bson_read_cstring(data, offset):
    end = data.index(b'\x00', offset)
    return data[offset:end].decode('utf-8', errors='replace'), end + 1


def _bson_read_string(data, offset):
    length = struct.unpack_from('<i', data, offset)[0]
    offset += 4
    s = data[offset:offset + length - 1].decode('utf-8', errors='replace')
    offset += length
    return s, offset


def _format_dotnet_guid(raw16):
    """.NET Guid.ToByteArray() layout: first 3 fields little-endian, last 2 big-endian."""
    b = raw16
    reordered = bytes([b[3], b[2], b[1], b[0], b[5], b[4], b[7], b[6]]) + b[8:16]
    return str(uuid.UUID(bytes=reordered))


def _bson_parse_element(data, offset):
    etype = data[offset]
    offset += 1
    name, offset = _bson_read_cstring(data, offset)

    if etype == 0x01:  # double
        val = struct.unpack_from('<d', data, offset)[0]; offset += 8
    elif etype == 0x02:  # string
        val, offset = _bson_read_string(data, offset)
    elif etype == 0x03:  # embedded document
        val, offset = _bson_parse_document(data, offset)
    elif etype == 0x04:  # array (document with numeric string keys)
        doc, offset = _bson_parse_document(data, offset)
        try:
            val = [doc[k] for k in sorted(doc.keys(), key=lambda x: int(x))]
        except Exception:
            val = list(doc.values())
    elif etype == 0x05:  # binary (GUIDs use this, subtype 0x00/0x04, 16 bytes)
        blen = struct.unpack_from('<i', data, offset)[0]; offset += 4
        subtype = data[offset]; offset += 1
        raw = data[offset:offset + blen]; offset += blen
        if subtype in (0x00, 0x04) and blen == 16:
            val = _format_dotnet_guid(raw)
        else:
            val = raw
    elif etype == 0x08:  # boolean
        val = bool(data[offset]); offset += 1
    elif etype == 0x09:  # UTC datetime (int64 ms since epoch)
        val = struct.unpack_from('<q', data, offset)[0]; offset += 8
    elif etype == 0x0A:  # null
        val = None
    elif etype == 0x10:  # int32
        val = struct.unpack_from('<i', data, offset)[0]; offset += 4
    elif etype == 0x11:  # timestamp
        val = struct.unpack_from('<Q', data, offset)[0]; offset += 8
    elif etype == 0x12:  # int64
        val = struct.unpack_from('<q', data, offset)[0]; offset += 8
    elif etype == 0x13:  # decimal128 (kept raw — unused by domain model fields)
        val = data[offset:offset + 16]; offset += 16
    elif etype == 0x07:  # ObjectId
        val = data[offset:offset + 12].hex(); offset += 12
    elif etype in (0xFF, 0x7F, 0x06):  # min/max key, undefined — no value bytes
        val = None
    else:
        raise ValueError(f"Unsupported BSON element type 0x{etype:02x} at offset {offset} (field {name!r})")

    return name, val, offset


def _bson_parse_document(data, offset):
    total_len = struct.unpack_from('<i', data, offset)[0]
    doc_end = offset + total_len
    offset += 4
    result = {}
    while offset < doc_end - 1:
        name, val, offset = _bson_parse_element(data, offset)
        result[name] = val
    return result, doc_end


def parse_mxunit_bson(file_bytes):
    """Parses a raw Mendix .mxunit file (a BSON document) into a nested dict."""
    doc, _ = _bson_parse_document(file_bytes, 0)
    return doc


def _mxunit_path_for_unit_id(mprcontents_path, unit_id_bytes):
    """
    The .mxunit filename IS the unit's own GUID, stored under
    mprcontents/<guid[0:2]>/<guid[2:4]>/<guid>.mxunit — deterministic, no
    scanning required.
    """
    guid_str = _format_dotnet_guid(bytes(unit_id_bytes))
    return os.path.join(mprcontents_path, guid_str[0:2], guid_str[2:4], f"{guid_str}.mxunit")


def _load_mxunit_dict(mprcontents_path, unit_id_bytes):
    """Reads + BSON-decodes a single unit's content file. Returns None on any failure."""
    path = _mxunit_path_for_unit_id(mprcontents_path, unit_id_bytes)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "rb") as f:
            raw = f.read()
        return parse_mxunit_bson(raw)
    except Exception:
        return None


def _extract_entities_and_raw_associations(dm_dict):
    """
    Converts a decoded 'DomainModels$DomainModel' BSON dict into:
      - entities: {name: [(type, attr_name), ...]}
      - raw_associations: [(parent_guid, child_guid, assoc_name, assoc_type), ...]
        (GUIDs left UNRESOLVED here — resolution happens in a later pass using
        a global GUID map so cross-module associations, e.g. to
        Administration.Account, aren't silently dropped just because the
        referenced entity lives in a different module's DomainModel unit)
      - raw_cross_associations: [(parent_guid, child_qualified_name, assoc_name,
        assoc_type), ...] — Mendix stores associations that cross OUTSIDE the
        normal module dependency graph (e.g. to the built-in System.User) in a
        SEPARATE 'CrossAssociations' array, where the child is given directly
        as a qualified name string like "System.User" or
        "Administration.Account" rather than a resolvable GUID pointer.
      - local_entity_map: {entity_guid: entity_name} for THIS module only
      - entity_meta: {name: {"persistent": bool, "extends": str|None}} — used
        to badge entities in the diagram the same way Studio Pro colors them
        (blue = persistent, orange = non-persistent)

    Every Mendix-serialized list has a stray leading non-dict marker element
    (always int 3, a fixed internal format tag — not real data), so non-dict
    list items are simply skipped.
    """
    entities = {}
    local_entity_map = {}
    entity_meta = {}

    for item in dm_dict.get('Entities', []) or []:
        if not isinstance(item, dict):
            continue
        name = item.get('Name')
        guid = item.get('$ID')
        if not name or not guid:
            continue
        local_entity_map[guid] = name

        attrs = []
        for a in item.get('Attributes', []) or []:
            if not isinstance(a, dict):
                continue
            a_name = a.get('Name')
            new_type = a.get('NewType') if isinstance(a.get('NewType'), dict) else {}
            type_raw = new_type.get('$Type', '') or ''
            clean_type = type_raw.replace('DomainModels$', '').replace('AttributeType', '').strip() or 'unknown'
            if a_name:
                attrs.append((clean_type.lower(), a_name))
        entities[name] = attrs

        gen = item.get('MaybeGeneralization') if isinstance(item.get('MaybeGeneralization'), dict) else {}
        gen_type = gen.get('$Type', '')
        if gen_type == 'DomainModels$NoGeneralization':
            persistent = gen.get('Persistable', True)
            extends = None
        elif gen_type == 'DomainModels$Generalization':
            # Inherits from another entity (possibly a System entity like
            # System.FileDocument) — best-effort default to persistent=True
            # since chasing the full inheritance chain isn't done here.
            persistent = True
            extends = gen.get('Generalization')
        else:
            persistent = True
            extends = None
        entity_meta[name] = {"persistent": bool(persistent), "extends": extends}

    raw_associations = []
    for item in dm_dict.get('Associations', []) or []:
        if not isinstance(item, dict):
            continue
        a_name = item.get('Name')
        parent_guid = item.get('ParentPointer')
        child_guid = item.get('ChildPointer')
        a_type = item.get('Type') or 'Reference'  # 'Reference' or 'ReferenceSet'
        if a_name and parent_guid and child_guid:
            raw_associations.append((parent_guid, child_guid, a_name, a_type))

    raw_cross_associations = []
    for item in dm_dict.get('CrossAssociations', []) or []:
        if not isinstance(item, dict):
            continue
        a_name = item.get('Name')
        parent_guid = item.get('ParentPointer')
        child_qualified_name = item.get('Child')  # e.g. "System.User", "Administration.Account"
        a_type = item.get('Type') or 'Reference'
        if a_name and parent_guid and child_qualified_name:
            raw_cross_associations.append((parent_guid, child_qualified_name, a_name, a_type))

    return entities, raw_associations, raw_cross_associations, local_entity_map, entity_meta


def _derive_unresolved_label(a_name, known_side_name):
    """
    When one side of an association can't be resolved via the global entity
    map (typically a genuinely built-in System entity like System.User,
    which isn't stored as a regular Unit in the project's own tree at all),
    derive a readable stub label from the association's own name instead of
    dropping the relationship. Mendix association names follow a
    'ParentName_RoleName' convention (e.g. PurchaseRequest_Requester), so
    stripping the KNOWN side's name off usually leaves a meaningful label
    (e.g. 'Requester').
    """
    if known_side_name:
        if a_name.startswith(known_side_name + "_"):
            remainder = a_name[len(known_side_name) + 1:]
        elif a_name.endswith("_" + known_side_name):
            remainder = a_name[: -(len(known_side_name) + 1)]
        else:
            remainder = a_name
    else:
        remainder = a_name
    remainder = re.sub(r'[^A-Za-z0-9_]', '_', remainder).strip('_')
    return remainder if remainder else "Entity"


def _parse_domain_model_from_project_new_schema(project_path, mpr_path):
    """
    Newer Git-friendly Mendix project format: Unit table (UnitID/ContainerID/
    ContainmentName) + external mprcontents/*.mxunit BSON files. Returns
    modules_data or {} if this project doesn't use this schema/layout.

    Two-pass approach:
      Pass 1 — decode every module's DomainModel, collecting its own entities
                plus a GLOBAL entity-GUID -> (module, entity_name) map.
      Pass 2 — resolve every association's Parent/ChildPointer GUIDs against
                that GLOBAL map, so an association pointing at an entity in a
                different module (e.g. PurchaseRequest_Requester ->
                Administration.Account) still gets included, with a
                lightweight stub box added for the foreign entity so the
                relationship has a visible endpoint.
    """
    mprcontents_path = os.path.join(project_path, "mprcontents")
    if not os.path.isdir(mprcontents_path):
        return {}

    try:
        conn = sqlite3.connect(mpr_path)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {r[0] for r in cur.fetchall()}
        if "Unit" not in tables:
            conn.close()
            return {}
        cur.execute("SELECT UnitID, ContainerID, ContainmentName FROM Unit WHERE ContainmentName IN ('Modules', 'DomainModel')")
        rows = cur.fetchall()
        conn.close()
    except Exception:
        return {}

    module_unit_ids = set()
    domainmodel_rows = []
    for unit_id, container_id, containment_name in rows:
        if containment_name == 'Modules':
            module_unit_ids.add(bytes(unit_id))
        elif containment_name == 'DomainModel':
            domainmodel_rows.append((bytes(unit_id), bytes(container_id)))

    # --- Pass 1: per-module entities + raw (unresolved) associations ---
    parsed_modules = {}     # module_name -> {"entities": {...}, "raw_associations": [...]}
    global_entity_map = {}  # entity_guid -> (module_name, entity_name)

    for dm_unit_id, dm_container_id in domainmodel_rows:
        if dm_container_id not in module_unit_ids:
            continue  # DomainModel not directly owned by a top-level Module — skip

        module_dict = _load_mxunit_dict(mprcontents_path, dm_container_id)
        module_name = module_dict.get('Name') if module_dict else None
        if not module_name:
            continue

        dm_dict = _load_mxunit_dict(mprcontents_path, dm_unit_id)
        if not dm_dict:
            continue

        entities, raw_associations, raw_cross_associations, local_entity_map, entity_meta = _extract_entities_and_raw_associations(dm_dict)
        if not entities:
            continue

        if module_name not in parsed_modules:
            parsed_modules[module_name] = {"entities": {}, "raw_associations": [], "raw_cross_associations": [], "entity_meta": {}}
        parsed_modules[module_name]["entities"].update(entities)
        parsed_modules[module_name]["raw_associations"].extend(raw_associations)
        parsed_modules[module_name]["raw_cross_associations"].extend(raw_cross_associations)
        parsed_modules[module_name]["entity_meta"].update(entity_meta)

        for guid, ent_name in local_entity_map.items():
            global_entity_map[guid] = (module_name, ent_name)

    # --- Pass 2: aggregate ALL raw associations from ALL modules, then show
    # each one in EVERY module touched by either endpoint entity. Mendix
    # stores an association's Unit row in whichever single module was open
    # in Studio Pro when it was drawn, but Studio Pro's own domain model
    # *viewer* still displays that association in any module where either
    # entity lives — e.g. PurchaseRequest_Requester is stored under whatever
    # module owns the Unit, but shows in BOTH ProcureFlow's and
    # Administration's domain model views. We replicate that here instead of
    # only looking at each module's own stored association list.
    modules_data = {
        module_name: {
            "entities": dict(data["entities"]),
            "associations": [],
            "entity_meta": dict(data.get("entity_meta", {})),
        }
        for module_name, data in parsed_modules.items()
    }

    all_raw_associations = []
    for data in parsed_modules.values():
        all_raw_associations.extend(data["raw_associations"])

    for parent_guid, child_guid, a_name, a_type in all_raw_associations:
        parent_info = global_entity_map.get(parent_guid)
        child_info = global_entity_map.get(child_guid)

        if not parent_info and not child_info:
            continue  # both sides unresolvable — nothing useful to render

        # One side is a genuinely built-in entity (e.g. System.User), which
        # is NOT stored as a regular Unit in the project's own tree at all —
        # no amount of module-scanning will ever find its GUID. Rather than
        # silently dropping the whole association, derive a readable stub
        # label from the association's own name: Mendix names follow a
        # 'ParentName_RoleName' convention (e.g. PurchaseRequest_Requester),
        # so the unresolved side's role name is usually right there in the name.
        if not child_info:
            child_mod, child_ent = "External", _derive_unresolved_label(a_name, parent_info[1] if parent_info else None)
        else:
            child_mod, child_ent = child_info

        if not parent_info:
            parent_mod, parent_ent = "External", _derive_unresolved_label(a_name, child_info[1] if child_info else None)
        else:
            parent_mod, parent_ent = parent_info

        for display_mod in {parent_mod, child_mod}:
            if display_mod not in modules_data:
                if display_mod == "External":
                    modules_data[display_mod] = {"entities": {}, "associations": [], "entity_meta": {}}
                else:
                    continue

            # Same-module endpoints keep their plain name; the OTHER module's
            # (or an unresolved External) endpoint gets a qualified stub label
            # + a lightweight stub box so the relationship has a visible node
            # in THIS module's view.
            parent_label = parent_ent if parent_mod == display_mod else f"{parent_mod}_{parent_ent}"
            child_label = child_ent if child_mod == display_mod else f"{child_mod}_{child_ent}"

            if parent_mod != display_mod and parent_label not in modules_data[display_mod]["entities"]:
                modules_data[display_mod]["entities"][parent_label] = []
            if child_mod != display_mod and child_label not in modules_data[display_mod]["entities"]:
                modules_data[display_mod]["entities"][child_label] = []

            tup = (parent_label, child_label, a_name, a_type)
            if tup not in modules_data[display_mod]["associations"]:
                modules_data[display_mod]["associations"].append(tup)

    # --- Pass 2b: resolve CrossAssociations. These are stored separately by
    # Mendix for anything crossing OUTSIDE the normal module dependency graph
    # (most commonly a reference to the built-in System.User) — the child
    # side is given directly as a qualified name string (e.g. "System.User",
    # "Administration.Account") rather than a resolvable GUID pointer, which
    # is actually simpler to handle: no GUID lookup needed for that side at all.
    all_raw_cross_associations = []
    for data in parsed_modules.values():
        all_raw_cross_associations.extend(data.get("raw_cross_associations", []))

    for parent_guid, child_qualified_name, a_name, a_type in all_raw_cross_associations:
        parent_info = global_entity_map.get(parent_guid)
        if not parent_info:
            continue  # can't even resolve the parent side — nothing useful to render

        parent_mod, parent_ent = parent_info

        if "." in child_qualified_name:
            child_mod, child_ent = child_qualified_name.split(".", 1)
        else:
            child_mod, child_ent = "System", child_qualified_name

        for display_mod in {parent_mod, child_mod}:
            if display_mod not in modules_data:
                modules_data[display_mod] = {"entities": {}, "associations": [], "entity_meta": {}}

            parent_label = parent_ent if parent_mod == display_mod else f"{parent_mod}_{parent_ent}"
            child_label = child_ent if child_mod == display_mod else f"{child_mod}_{child_ent}"

            # setdefault (not a conditional add) so this also covers the case
            # where display_mod is a brand-new synthetic module (e.g. "System")
            # that needs its own entity box created too, not just the foreign side.
            modules_data[display_mod]["entities"].setdefault(parent_label, [])
            modules_data[display_mod]["entities"].setdefault(child_label, [])

            tup = (parent_label, child_label, a_name, a_type)
            if tup not in modules_data[display_mod]["associations"]:
                modules_data[display_mod]["associations"].append(tup)

    return modules_data


def is_microflow_or_page(name):
    """Filter to ensure Microflows, Pages, and Layouts are NEVER treated as Entities."""
    name_lower = name.lower()
    # Microflows prefixes
    if any(name.startswith(p) for p in ["ACT_", "SUB_", "DS_", "BCo_", "ACo_", "BDe_", "ADe_", "VAL_", "TOOL_", "OCh_", "IVK_", "Sn_"]):
        return True
    # Pages suffixes
    if any(name_lower.endswith(s) for s in ["_overview", "_newedit", "_review", "_select", "_detail", "_layout", "_images", "breadcrumbs", "dynamicbreadcrumbs", "adminlayout"]):
        return True
    return False

def _extract_entities_and_associations_for_module(domain_text, mod_name):
    """
    Shared regex-based extraction (module-scoped) against an already-decompressed
    domain_text string. Used by BOTH the uploaded-.mpk flow and the local
    Project Path (.mpr) flow so the parsing logic lives in exactly one place.
    Returns (entities_dict, associations_list).
    """
    entities = {}
    entity_candidates = set()

    # Pattern 1: Module.EntityName
    for m in re.finditer(rf'\b{re.escape(mod_name)}[.\$]([A-Za-z0-9_]+)\b', domain_text, re.IGNORECASE):
        e = m.group(1)
        if not is_microflow_or_page(e) and len(e) > 1 and not e.startswith(('System', 'Mx', 'Atlas', '_')):
            entity_candidates.add(e)

    # Pattern 2: DomainModels$Entity JSON/XML definition
    for m in re.finditer(r'DomainModels[\.\$]Entity[^>]*?Name["\s:]+([A-Za-z0-9_]+)', domain_text, re.IGNORECASE):
        e = m.group(1)
        if not is_microflow_or_page(e) and len(e) > 1 and not e.startswith(('System', 'Mx', 'Atlas', '_')):
            entity_candidates.add(e)

    # Associations (Strictly Relationship lines)
    detected_assocs = []
    for m in re.finditer(r'DomainModels[\.\$]Association[^>]*?Name["\s:]+([A-Za-z0-9_]+)', domain_text, re.IGNORECASE):
        a_name = m.group(1)
        if "_" in a_name:
            parts = a_name.split("_")
            p, c = parts[0], parts[1]
            if not is_microflow_or_page(p) and not is_microflow_or_page(c):
                detected_assocs.append((p, c, a_name))
                entity_candidates.add(p)
                if not c.startswith(('System', 'Mx')):
                    entity_candidates.add(c)

    for p in list(entity_candidates):
        for m in re.finditer(rf'\b{re.escape(p)}_([A-Za-z0-9_]+)\b', domain_text):
            c = m.group(1)
            if c != p and not is_microflow_or_page(c) and len(c) > 1:
                a_name = f"{p}_{c}"
                if (p, c, a_name) not in detected_assocs:
                    detected_assocs.append((p, c, a_name))

    for e in entity_candidates:
        # Ensure association names are NOT added as standalone entities!
        if not any(e == a[2] for a in detected_assocs):
            entities.setdefault(e, [])

    # Regex-based detection can't reliably tell Reference from ReferenceSet,
    # so default to 'Reference' (the common case) — kept as a 4th element so
    # this shape matches the BSON-based project-path parser's output exactly.
    associations = []
    for p, c, a_name in detected_assocs:
        tup = (p, c, a_name, 'Reference')
        if tup not in associations:
            associations.append(tup)

    # Attributes for identified Entities
    for e_name in list(entities.keys()):
        attr_matches = re.findall(rf'{re.escape(e_name)}[^A-Za-z0-9_].*?([A-Za-z0-9_]+)AttributeType.*?([A-Za-z0-9_]+)', domain_text, re.IGNORECASE)
        for a_type, a_name in attr_matches[:10]:
            clean_t = a_type.replace('AttributeType', '').replace('Type', '').lower()
            if len(a_name) > 1 and len(clean_t) > 1 and not is_microflow_or_page(a_name):
                if (clean_t, a_name) not in entities[e_name]:
                    entities[e_name].append((clean_t, a_name))

    return entities, associations


def _auto_discover_module_names_from_text(domain_text):
    """
    Fallback module-name discovery that doesn't rely on any on-disk folder
    layout at all: scans the decompressed .mpr content directly for
    'ModuleName.Something' qualified references (the same shape Mendix uses
    for entity/association ownership) and treats the distinct capitalized
    prefixes as candidate module names. Used when folder-based discovery
    (_discover_project_modules) finds nothing — e.g. Git-managed projects
    that don't scaffold modules/<Name>/ folders on disk.
    """
    noise = {
        'System', 'Mx', 'Atlas', 'DomainModels', 'Microflows', 'Pages', 'Nanoflows',
        'Nanoflow', 'Projects', 'Workflows', 'Workflow', 'Menus', 'Navigation',
        'Settings', 'Texts', 'Images', 'Layouts', 'Security', 'Rules'
    }
    candidates = set()
    for m in re.finditer(r'\b([A-Z][A-Za-z0-9]{1,40})\.[A-Za-z_][A-Za-z0-9_]*\b', domain_text):
        name = m.group(1)
        if name not in noise:
            candidates.add(name)
    return sorted(candidates)


def _extract_modules_data_from_mpr_file(mpr_path, module_names=None):
    """
    100% PURE DOMAIN MODEL PARSER (ZERO HARDCODING & ZERO BLACKLIST):
    - Target: ONLY SQLite units of type 'DomainModels$DomainModel' (eliminates all Microflows & Pages).
    - Associations: Handled strictly as relationship lines (never as standalone entity boxes).
    Works directly against a Mendix .mpr SQLite file on disk (either the real
    project .mpr, or a temp copy extracted from an uploaded .mpk).

    If module_names is None or empty, module names are auto-discovered
    directly from the decompressed .mpr content (see
    _auto_discover_module_names_from_text) rather than relying on any
    particular on-disk folder layout.
    """
    if not os.path.exists(mpr_path):
        return {m: {"entities": {}, "associations": []} for m in (module_names or [])}

    try:
        conn = sqlite3.connect(mpr_path)
        cur = conn.cursor()

        # 🎯 QUERY STRICTLY DOMAIN MODEL UNITS ONLY (Ignores Microflows, Pages, Layouts!)
        cur.execute("""
            SELECT _Contents FROM _Unit
            WHERE _Type LIKE '%DomainModel%' OR _Type LIKE '%Entities%'
        """)
        rows = cur.fetchall()

        # Fallback if SQLite table format differs
        if not rows:
            cur.execute("SELECT _Contents FROM _Unit WHERE _Contents IS NOT NULL")
            rows = cur.fetchall()

        domain_dump_strings = []
        for row in rows:
            if isinstance(row[0], bytes):
                domain_dump_strings.extend(extract_all_strings_from_blob(row[0]))
        domain_text = " ".join(domain_dump_strings)
        conn.close()
    except Exception:
        return {m: {"entities": {}, "associations": []} for m in (module_names or [])}

    if not module_names:
        module_names = _auto_discover_module_names_from_text(domain_text)

    modules_data = {m: {"entities": {}, "associations": []} for m in module_names}
    for mod_name in module_names:
        entities, associations = _extract_entities_and_associations_for_module(domain_text, mod_name)
        modules_data[mod_name]["entities"] = entities
        modules_data[mod_name]["associations"] = associations

    return modules_data


def parse_domain_model_from_mpk_files(uploaded_files):
    """
    Builds a raw modules_data dict {module_name: {entities: {...}, associations: [...]}}
    strictly from uploaded .mpk file(s). No mermaid rendering here (kept separate so
    callers can cache/inspect the raw structure before building a diagram).
    """
    modules_data = {}
    if not uploaded_files:
        return modules_data

    if not isinstance(uploaded_files, list):
        uploaded_files = [uploaded_files]

    for f in uploaded_files:
        if f is None or not f.name.lower().endswith(".mpk"):
            continue

        mod_name = os.path.splitext(f.name)[0]
        mod_name = re.sub(r'(_[0-9]+|\.[0-9]+|\.mpk)$', '', mod_name, flags=re.IGNORECASE)

        if mod_name not in modules_data:
            modules_data[mod_name] = {"entities": {}, "associations": []}

        try:
            f.seek(0)
            zip_buffer = io.BytesIO(f.read())
            with zipfile.ZipFile(zip_buffer, 'r') as zip_ref:
                for info in zip_ref.infolist():
                    if info.filename.endswith(('.mpr', '.db')):
                        temp_mpr = f"temp_dm_{uuid.uuid4().hex}.mpr"
                        try:
                            mpr_bytes = zip_ref.read(info)
                            with open(temp_mpr, "wb") as tf:
                                tf.write(mpr_bytes)

                            per_module = _extract_modules_data_from_mpr_file(temp_mpr, [mod_name])
                            entry = per_module.get(mod_name, {"entities": {}, "associations": []})

                            for e, attrs in entry["entities"].items():
                                modules_data[mod_name]["entities"].setdefault(e, [])
                                for a in attrs:
                                    if a not in modules_data[mod_name]["entities"][e]:
                                        modules_data[mod_name]["entities"][e].append(a)

                            for assoc in entry["associations"]:
                                if assoc not in modules_data[mod_name]["associations"]:
                                    modules_data[mod_name]["associations"].append(assoc)
                        except Exception:
                            pass
                        finally:
                            if os.path.exists(temp_mpr):
                                try: os.remove(temp_mpr)
                                except Exception: pass
        except Exception:
            continue

    return modules_data


def _find_project_mpr_file(project_path):
    """Locates the main Mendix .mpr (SQLite project database) file at the project root."""
    try:
        for entry in os.listdir(project_path):
            if entry.lower().endswith(".mpr"):
                return os.path.join(project_path, entry)
    except Exception:
        pass
    return None


def _discover_project_modules(project_path):
    """
    Real Mendix project layout: user-created modules live under
    <project>/modules/<ModuleName>/ — that's the primary, reliable source.
    Some older/edge-case project layouts kept module folders directly at the
    project root, so that's kept as a fallback if 'modules/' isn't present
    or yields nothing.
    """
    modules_dir = os.path.join(project_path, "modules")
    candidates = []
    if os.path.isdir(modules_dir):
        try:
            for entry in os.listdir(modules_dir):
                full = os.path.join(modules_dir, entry)
                if os.path.isdir(full) and not entry.startswith('.'):
                    candidates.append(entry)
        except Exception:
            pass
        if candidates:
            return candidates

    # Legacy fallback: treat top-level project folders as candidate modules.
    excluded = {
        "theme", "resources", "deployment", "javasource", "widgets", "javascriptsource",
        ".mendixcloud", ".git", ".idea", "customwidgets", "settings", "releases",
        "userlib", "log", "images", ".vscode", "node_modules", "modules",
        "app-bundler", "extensions", "mendix-checker", "mlsource", "mprcontents",
        "theme-cache", "themesource", "vendorlib", ".mendix-cache"
    }
    try:
        for entry in os.listdir(project_path):
            full = os.path.join(project_path, entry)
            if os.path.isdir(full) and not entry.startswith('.') and entry.lower() not in excluded:
                candidates.append(entry)
    except Exception:
        pass
    return candidates


def parse_domain_model_from_project(project_path):
    """
    Builds a raw modules_data dict directly from the local Mendix Project Path's
    .mpr file (preferred source — no need to upload/export a .mpk at all).

    Tries the newer Git-friendly schema first (Unit table + external
    mprcontents/*.mxunit BSON files, used by "Use Git version control"
    projects) since it gives exact, authoritative module/entity/attribute/
    association data straight from Mendix's own object model — no regex
    guessing involved. Falls back to the legacy single-file schema (_Unit
    table with inline _Contents blobs, older/non-Git projects) if the new
    schema isn't present.
    """
    if not project_path or not os.path.exists(project_path):
        return {}

    mpr_path = _find_project_mpr_file(project_path)
    if not mpr_path:
        return {}

    modules_data = _parse_domain_model_from_project_new_schema(project_path, mpr_path)
    if modules_data:
        return modules_data

    # Legacy fallback: single-file .mpr with inline _Contents blobs.
    candidate_modules = _discover_project_modules(project_path)
    return _extract_modules_data_from_mpr_file(mpr_path, candidate_modules if candidate_modules else None)


def build_mermaid_from_modules_data(modules_data):
    """Renders CLEAN 100% VALID MERMAID ERD SYNTAX from a modules_data dict."""
    module_diagrams = {}
    all_combined_lines = ["erDiagram"]
    total_entities_count = 0
    total_assocs_count = 0

    for m_name, m_info in modules_data.items():
        if not m_info["entities"]:
            continue

        m_lines = ["erDiagram"]
        unique_assocs = []

        for assoc in m_info["associations"]:
            # Defensive: accept both the newer 4-tuple (p, c, name, type) and
            # any legacy 3-tuple (p, c, name), defaulting type to 'Reference'.
            p, c, name = assoc[0], assoc[1], assoc[2]
            a_type = assoc[3] if len(assoc) > 3 else 'Reference'
            tup = (p, c, name, a_type)
            if tup not in unique_assocs:
                unique_assocs.append(tup)

        # Real Mendix cardinality: 'Reference' = many-to-one, 'ReferenceSet' =
        # many-to-many. Label matches Studio Pro (just the association name).
        for p, c, name, a_type in unique_assocs:
            safe_label = re.sub(r'[^A-Za-z0-9_ ]', '_', name)
            connector = "}o--o{" if a_type == "ReferenceSet" else "||--o{"

            m_lines.append(f'    {p} {connector} {c} : "{safe_label}"')
            all_combined_lines.append(f'    {p} {connector} {c} : "{safe_label}"')
            total_assocs_count += 1

        # Render Entities — badge persistent (🔵) vs non-persistent (🟠) and
        # annotate generalization, matching Studio Pro's blue/orange entity
        # header convention. Uses Mermaid's entity-alias syntax
        # (id["display label"]) so the identifier associations rely on is
        # untouched — only the visible header text changes.
        entity_meta = m_info.get("entity_meta", {})
        for e_name, attrs in m_info["entities"].items():
            total_entities_count += 1
            meta = entity_meta.get(e_name, {})
            persistent = meta.get("persistent", True)
            extends = meta.get("extends")

            badge = "🔵" if persistent else "🟠"
            label = f"{e_name} {badge}"
            if extends:
                safe_extends = re.sub(r'["\n]', '', str(extends))
                label += f" (extends {safe_extends})"
            safe_label = re.sub(r'["\n]', '', label)
            header = f'{e_name}["{safe_label}"]'

            if attrs:
                m_lines.append(f"    {header} {{")
                all_combined_lines.append(f"    {header} {{")
                for a_type, a_name in attrs[:8]:
                    m_lines.append(f"        {a_type} {a_name}")
                    all_combined_lines.append(f"        {a_type} {a_name}")
                m_lines.append("    }")
                all_combined_lines.append("    }")
            else:
                m_lines.append(f"    {header} {{\n        string id\n    }}")
                all_combined_lines.append(f"    {header} {{\n        string id\n    }}")

        module_diagrams[m_name] = "\n".join(m_lines)

    all_combined_mermaid = "\n".join(all_combined_lines)
    summary = f"✅ {total_entities_count} Core Domain Entities and {total_assocs_count} Associations mapped across {len(module_diagrams)} module(s)!"

    return all_combined_mermaid, summary, module_diagrams


def compute_domain_model_signature(project_path=None, uploaded_files=None):
    """
    Cheap signature (no parsing!) used to detect whether the cached Domain Model
    is stale. Local Project Path uses the .mpr file's mtime; uploaded .mpk uses
    name+size. This lets callers avoid reparsing on every AI request.
    """
    if project_path and os.path.exists(project_path):
        mpr_path = _find_project_mpr_file(project_path)
        if mpr_path:
            try:
                mtime = os.path.getmtime(mpr_path)
                return f"project::{mpr_path}::{mtime}"
            except Exception:
                return f"project::{mpr_path}"

    if uploaded_files:
        files = uploaded_files if isinstance(uploaded_files, list) else [uploaded_files]
        mpk_files = [f for f in files if f is not None and f.name.lower().endswith(".mpk")]
        if mpk_files:
            parts = sorted(f"{f.name}:{getattr(f, 'size', 0)}" for f in mpk_files)
            return "upload::" + "|".join(parts)

    return None


def generate_domain_model(project_path=None, uploaded_files=None):
    """
    Orchestrator: PREFERS the local Mendix Project Path when available & valid;
    otherwise falls back to any uploaded .mpk file(s).

    Returns: (all_mermaid, summary, module_diagrams, modules_data, source_label)
             or (None, message, {}, {}, None) if nothing could be parsed.
    """
    if project_path and os.path.exists(project_path):
        mpr_path = _find_project_mpr_file(project_path)
        if mpr_path:
            modules_data = parse_domain_model_from_project(project_path)
            modules_data = {m: d for m, d in modules_data.items() if d["entities"]}
            if modules_data:
                all_mermaid, summary, module_diagrams = build_mermaid_from_modules_data(modules_data)
                summary += f" (Source: Local Project Path — '{os.path.basename(mpr_path)}')"
                return all_mermaid, summary, module_diagrams, modules_data, f"project::{mpr_path}"
        else:
            return None, "⚠️ No .mpr file found in the configured Project Path.", {}, {}, None

    # Fallback: uploaded .mpk file(s)
    if uploaded_files:
        modules_data = parse_domain_model_from_mpk_files(uploaded_files)
        modules_data = {m: d for m, d in modules_data.items() if d["entities"]}
        if modules_data:
            all_mermaid, summary, module_diagrams = build_mermaid_from_modules_data(modules_data)
            summary += " (Source: Uploaded .mpk file(s))"
            return all_mermaid, summary, module_diagrams, modules_data, "upload"

    return None, "No .mpk file or valid Project Path detected. Configure the Project Path or attach a .mpk file.", {}, {}, None


def extract_domain_model_mermaid(uploaded_files):
    """Legacy wrapper (uploaded-.mpk-only) kept for backwards compatibility."""
    modules_data = parse_domain_model_from_mpk_files(uploaded_files)
    modules_data = {m: d for m, d in modules_data.items() if d["entities"]}
    if not modules_data:
        return None, "No .mpk file detected in the uploader.", {}
    return build_mermaid_from_modules_data(modules_data)


def extract_referenced_entities_from_text(text):
    """Finds Module.Entity-shaped tokens inside arbitrary reference text (page hierarchy, SCSS, etc)."""
    refs = set()
    if not text:
        return refs
    for m in re.finditer(r'\b([A-Za-z0-9_]+)\.([A-Za-z0-9_]+)\b', text):
        refs.add((m.group(1), m.group(2)))
    return refs


def build_relevant_domain_context(modules_data, reference_text="", max_entities=15):
    """
    Token-efficient Domain Model context builder for the AI. Instead of dumping the
    entire Domain Model into every prompt, this filters down to only the entities
    actually referenced by the current page/SCSS context (e.g. DataView/DataGrid
    Entity bindings picked up by parse_deep_page_hierarchy), plus their direct
    associations. Falls back to a compact names-only overview if no direct
    reference could be matched (e.g. no .mpk attached yet).
    """
    if not modules_data:
        return ""

    referenced = extract_referenced_entities_from_text(reference_text)
    selected = []
    for mod, info in modules_data.items():
        for ent in info.get("entities", {}).keys():
            if (mod, ent) in referenced:
                selected.append((mod, ent))

    if not selected:
        lines = ["🧬 DOMAIN MODEL OVERVIEW (names only — no direct entity binding detected on this page yet):"]
        count = 0
        for mod, info in modules_data.items():
            ent_names = list(info.get("entities", {}).keys())
            if not ent_names:
                continue
            lines.append(f" - Module '{mod}': " + ", ".join(ent_names[:20]))
            count += 1
            if count >= max_entities:
                break
        return "\n".join(lines)

    # Expand to directly-associated entities so relationships stay understandable
    expand_set = set(selected)
    for mod, info in modules_data.items():
        for assoc in info.get("associations", []):
            p, c = assoc[0], assoc[1]
            if (mod, p) in selected:
                expand_set.add((mod, c))
            if (mod, c) in selected:
                expand_set.add((mod, p))

    lines = ["🧬 RELEVANT DOMAIN MODEL CONTEXT (filtered to entities actually used on this page):"]
    seen = 0
    for mod, info in modules_data.items():
        ents = info.get("entities", {})
        for ent, attrs in ents.items():
            if (mod, ent) not in expand_set:
                continue
            seen += 1
            if seen > max_entities:
                break
            attr_str = ", ".join(f"{t}:{n}" for t, n in attrs[:10]) if attrs else "(no attributes detected)"
            lines.append(f" - {mod}.{ent} [{attr_str}]")

        assoc_lines = [
            f"   ↳ {mod}.{assoc[0]} -> {mod}.{assoc[1]} ({assoc[2]})"
            for assoc in info.get("associations", [])
            if (mod, assoc[0]) in expand_set or (mod, assoc[1]) in expand_set
        ]
        lines.extend(assoc_lines[:10])

    return "\n".join(lines)