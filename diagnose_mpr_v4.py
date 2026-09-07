"""
Diagnostic v4 — tests the theory that mprcontents files are stored under
mprcontents/<hex[0:2]>/<hex[2:4]>/<rest of hex or full hex> where hex is the
HEX encoding of the raw bytes behind the base64 ContentsHash column.

Run:
    python diagnose_mpr_v4.py "C:\\Users\\Owner\\Mendix\\ProcureFlowHub-AI_usage"
"""
import sys
import os
import sqlite3
import base64
import gzip
import zlib

def try_decompress(raw):
    """Try a few common compression schemes; return (method, text_or_none)."""
    for name, fn in [
        ("gzip", lambda b: gzip.decompress(b)),
        ("zlib", lambda b: zlib.decompress(b)),
        ("raw-utf8", lambda b: b),
    ]:
        try:
            out = fn(raw)
            text = out.decode("utf-8", errors="strict")
            return name, text
        except Exception:
            continue
    return None, None

def main():
    if len(sys.argv) < 2:
        print("Usage: python diagnose_mpr_v4.py <path to PROJECT FOLDER>")
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
    # Grab one hash per interesting ContainmentName, prioritizing DomainModel/Modules
    cur.execute("""
        SELECT ContainmentName, ContentsHash FROM Unit
        WHERE ContainmentName IN ('DomainModel', 'Modules', 'ModuleSecurity', 'ModuleSettings')
        AND ContentsHash IS NOT NULL AND ContentsHash != ''
        LIMIT 10
    """)
    samples = cur.fetchall()
    conn.close()

    print(f"[*] Testing {len(samples)} sample hashes against hex-sharded mprcontents layout...\n")

    for cn, b64hash in samples:
        try:
            raw_bytes = base64.b64decode(b64hash)
        except Exception as e:
            print(f"  {cn!r}: could not base64-decode hash {b64hash!r}: {e}")
            continue

        hex_hash = raw_bytes.hex()

        candidates = [
            os.path.join(mprcontents_path, hex_hash[0:2], hex_hash[2:4], hex_hash[4:]),
            os.path.join(mprcontents_path, hex_hash[0:2], hex_hash[2:]),
            os.path.join(mprcontents_path, hex_hash[0:2], hex_hash[2:4], hex_hash),
        ]

        found = None
        for c in candidates:
            if os.path.isfile(c):
                found = c
                break

        print(f"  ContainmentName={cn!r}")
        print(f"    base64 hash: {b64hash}")
        print(f"    hex hash:    {hex_hash}")
        if found:
            size = os.path.getsize(found)
            print(f"    ✅ FOUND: {found}  ({size} bytes)")
            with open(found, "rb") as f:
                raw = f.read()
            method, text = try_decompress(raw)
            if text is not None:
                print(f"    Decoded via: {method}  (length={len(text)} chars)")
                print(f"    --- First 500 chars ---")
                print("    " + text[:500].replace("\n", "\n    "))
                print(f"    -----------------------")
            else:
                print(f"    ⚠️ Could not decode as gzip/zlib/utf-8. First 40 raw bytes: {raw[:40]!r}")
        else:
            print(f"    ❌ Not found. Tried:")
            for c in candidates:
                print(f"       {c}")
            # Last resort: list what's actually in the shard folder
            shard_dir = os.path.join(mprcontents_path, hex_hash[0:2])
            if os.path.isdir(shard_dir):
                entries = os.listdir(shard_dir)
                print(f"    Contents of shard dir '{hex_hash[0:2]}' ({len(entries)} entries, first 10): {entries[:10]}")
        print()


if __name__ == "__main__":
    main()