"""
Diagnostic v5 — brute-force: walks the ENTIRE mprcontents tree, computes
base64(sha256(file_bytes)) for every actual file found, and checks it
against a target set of known ContentsHash values (for DomainModel and
Modules rows). This sidesteps guessing the folder-naming scheme entirely.

Run:
    python diagnose_mpr_v5.py "C:\\Users\\Owner\\Mendix\\ProcureFlowHub-AI_usage"

May take a little while depending on how many files are in mprcontents —
it prints progress every 2000 files.
"""
import sys
import os
import sqlite3
import base64
import hashlib
import gzip
import zlib

def try_decompress_preview(raw, limit=500):
    for name, fn in [("gzip", gzip.decompress), ("zlib", zlib.decompress), ("raw-utf8", lambda b: b)]:
        try:
            out = fn(raw)
            text = out.decode("utf-8", errors="strict")
            return name, text[:limit]
        except Exception:
            continue
    return None, None

def main():
    if len(sys.argv) < 2:
        print("Usage: python diagnose_mpr_v5.py <path to PROJECT FOLDER>")
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

    target_map = {h: cn for cn, h in targets}  # base64 hash -> ContainmentName
    print(f"[*] Looking for {len(target_map)} target hashes ({sum(1 for v in target_map.values() if v=='DomainModel')} DomainModel, {sum(1 for v in target_map.values() if v=='Modules')} Modules)\n")

    found_count = 0
    scanned = 0
    matches = []  # (path, containment_name, hash)

    for root, dirs, files in os.walk(mprcontents_path):
        for fname in files:
            fpath = os.path.join(root, fname)
            scanned += 1
            if scanned % 2000 == 0:
                print(f"    ...scanned {scanned} files so far, {found_count} matches found")
            try:
                with open(fpath, "rb") as f:
                    raw = f.read()
            except Exception:
                continue

            # Hash the raw file bytes as-is
            digest = base64.b64encode(hashlib.sha256(raw).digest()).decode("ascii")
            if digest in target_map:
                matches.append((fpath, target_map[digest], digest))
                found_count += 1
                if found_count >= len(target_map):
                    break
        if found_count >= len(target_map):
            break

    print(f"\n[*] Done. Scanned {scanned} files total. Found {found_count}/{len(target_map)} matches.\n")

    for fpath, cn, h in matches[:6]:
        size = os.path.getsize(fpath)
        print(f"  ✅ {cn} match: {fpath}  ({size} bytes)")
        with open(fpath, "rb") as f:
            raw = f.read()
        method, preview = try_decompress_preview(raw)
        if preview is not None:
            print(f"     Decoded via: {method}")
            print(f"     Preview: {preview[:300]!r}")
        else:
            print(f"     Raw first 40 bytes: {raw[:40]!r}")
        print()

    if not matches:
        print("!! No matches found even with a full brute-force scan.")
        print("   This likely means ContentsHash is NOT a simple sha256(file_bytes) of the")
        print("   stored file — could involve a different hash algo, or the hash covers the")
        print("   decompressed/original content while the file on disk is compressed differently,")
        print("   or content dedup uses a different key entirely. Let's inspect a random sample file directly.")
        # Grab one arbitrary real file so we can eyeball its raw shape
        for root, dirs, files in os.walk(mprcontents_path):
            if files:
                sample = os.path.join(root, files[0])
                print(f"\n   Sample file: {sample}")
                with open(sample, "rb") as f:
                    raw = f.read()
                print(f"   Size: {len(raw)} bytes")
                print(f"   First 60 raw bytes: {raw[:60]!r}")
                method, preview = try_decompress_preview(raw)
                if preview is not None:
                    print(f"   Decodes via: {method}")
                    print(f"   Preview: {preview[:300]!r}")
                break


if __name__ == "__main__":
    main()