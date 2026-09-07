"""
Diagnostic v6 — self-contained BSON decoder for Mendix .mxunit files.
Locates a DomainModel unit + its corresponding Modules unit, decodes both
from raw BSON, and pretty-prints their structure (truncated for readability)
so we can see the real schema (entity/attribute/association field names).

Run:
    python diagnose_mpr_v6.py "C:\\Users\\Owner\\Mendix\\ProcureFlowHub-AI_usage"
"""
import sys
import os
import sqlite3
import base64
import hashlib
import struct
import uuid


# ---------------------------------------------------------------------------
# Minimal BSON decoder (handles the element types Mendix .mxunit files use)
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
    b = raw16
    reordered = bytes([b[3], b[2], b[1], b[0], b[5], b[4], b[7], b[6]]) + b[8:16]
    return str(uuid.UUID(bytes=reordered))

def _bson_parse_element(data, offset):
    etype = data[offset]
    offset += 1
    name, offset = _bson_read_cstring(data, offset)

    if etype == 0x01:
        val = struct.unpack_from('<d', data, offset)[0]; offset += 8
    elif etype == 0x02:
        val, offset = _bson_read_string(data, offset)
    elif etype == 0x03:
        val, offset = _bson_parse_document(data, offset)
    elif etype == 0x04:
        doc, offset = _bson_parse_document(data, offset)
        try:
            val = [doc[k] for k in sorted(doc.keys(), key=lambda x: int(x))]
        except Exception:
            val = list(doc.values())
    elif etype == 0x05:
        blen = struct.unpack_from('<i', data, offset)[0]; offset += 4
        subtype = data[offset]; offset += 1
        raw = data[offset:offset + blen]; offset += blen
        if subtype in (0x00, 0x04) and blen == 16:
            val = _format_dotnet_guid(raw)
        else:
            val = raw
    elif etype == 0x08:
        val = bool(data[offset]); offset += 1
    elif etype == 0x09:
        val = struct.unpack_from('<q', data, offset)[0]; offset += 8
    elif etype == 0x0A:
        val = None
    elif etype == 0x10:
        val = struct.unpack_from('<i', data, offset)[0]; offset += 4
    elif etype == 0x11:
        val = struct.unpack_from('<Q', data, offset)[0]; offset += 8
    elif etype == 0x12:
        val = struct.unpack_from('<q', data, offset)[0]; offset += 8
    elif etype == 0x13:
        val = data[offset:offset + 16]; offset += 16
    elif etype == 0x07:
        val = data[offset:offset + 12].hex(); offset += 12
    elif etype in (0xFF, 0x7F, 0x06):
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
    doc, _ = _bson_parse_document(file_bytes, 0)
    return doc


# ---------------------------------------------------------------------------
# Pretty printer (truncated, for terminal readability)
# ---------------------------------------------------------------------------

def pretty_print(val, indent=0, max_depth=7, max_list_items=4, max_str_len=150):
    pad = "  " * indent
    if indent > max_depth:
        print(pad + "... (max depth reached)")
        return
    if isinstance(val, dict):
        for k, v in val.items():
            if isinstance(v, (dict, list)):
                print(f"{pad}{k}:")
                pretty_print(v, indent + 1, max_depth, max_list_items, max_str_len)
            else:
                vs = v
                if isinstance(vs, bytes):
                    vs = f"<bytes len={len(vs)}>"
                elif isinstance(vs, str) and len(vs) > max_str_len:
                    vs = vs[:max_str_len] + "...(truncated)"
                print(f"{pad}{k}: {vs!r}")
    elif isinstance(val, list):
        print(f"{pad}[list of {len(val)} items]")
        for i, item in enumerate(val[:max_list_items]):
            print(f"{pad}  - item[{i}]:")
            pretty_print(item, indent + 2, max_depth, max_list_items, max_str_len)
        if len(val) > max_list_items:
            print(f"{pad}  ... ({len(val) - max_list_items} more items)")
    else:
        print(f"{pad}{val!r}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print("Usage: python diagnose_mpr_v6.py <path to PROJECT FOLDER>")
        sys.exit(1)

    project_path = sys.argv[1]
    mpr_path = None
    for entry in os.listdir(project_path):
        if entry.lower().endswith(".mpr"):
            mpr_path = os.path.join(project_path, entry)
            break
    if not mpr_path:
        print("No .mpr found.")
        sys.exit(1)

    mprcontents_path = os.path.join(project_path, "mprcontents")

    conn = sqlite3.connect(mpr_path)
    cur = conn.cursor()
    cur.execute("""
        SELECT ContainmentName, ContentsHash FROM Unit
        WHERE ContainmentName IN ('DomainModel', 'Modules')
        AND ContentsHash IS NOT NULL AND ContentsHash != ''
    """)
    targets = cur.fetchall()
    conn.close()

    target_map = {h: cn for cn, h in targets}
    print(f"[*] Building hash->path index across mprcontents (one-time full scan)...")

    hash_to_path = {}
    scanned = 0
    for root, dirs, files in os.walk(mprcontents_path):
        for fname in files:
            fpath = os.path.join(root, fname)
            scanned += 1
            try:
                with open(fpath, "rb") as f:
                    raw = f.read()
            except Exception:
                continue
            digest = base64.b64encode(hashlib.sha256(raw).digest()).decode("ascii")
            if digest in target_map:
                hash_to_path[digest] = fpath
    print(f"    Scanned {scanned} files, resolved {len(hash_to_path)}/{len(target_map)} target hashes.\n")

    # Pick ONE DomainModel + its file, and print structure
    dm_hash = next((h for h, cn in target_map.items() if cn == 'DomainModel' and h in hash_to_path), None)
    mod_hash = next((h for h, cn in target_map.items() if cn == 'Modules' and h in hash_to_path), None)

    if mod_hash:
        print("=" * 70)
        print(f"MODULES unit structure ({hash_to_path[mod_hash]}):")
        print("=" * 70)
        with open(hash_to_path[mod_hash], "rb") as f:
            raw = f.read()
        try:
            doc = parse_mxunit_bson(raw)
            pretty_print(doc)
        except Exception as e:
            print(f"!! BSON parse failed: {e}")
        print()

    if dm_hash:
        print("=" * 70)
        print(f"DOMAINMODEL unit structure ({hash_to_path[dm_hash]}):")
        print("=" * 70)
        with open(hash_to_path[dm_hash], "rb") as f:
            raw = f.read()
        try:
            doc = parse_mxunit_bson(raw)
            pretty_print(doc)
        except Exception as e:
            print(f"!! BSON parse failed: {e}")


if __name__ == "__main__":
    main()