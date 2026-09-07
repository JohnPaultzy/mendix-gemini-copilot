"""
Diagnostic v3 — this Mendix project stores content externally (content-
addressable, via ContentsHash) in the 'mprcontents' folder rather than
inline blobs in the .mpr SQLite DB. This script maps out:
  1. The distinct ContainmentName values (tells us the unit tree "slot" names,
     e.g. Modules / DomainModel / Microflows / etc.)
  2. The mprcontents folder's actual on-disk layout
  3. Attempts to resolve one real ContentsHash to an actual file on disk

Run from the project root (folder that contains 'mprcontents' as a sibling
of App.mpr):
    python diagnose_mpr_v3.py "C:\\Users\\Owner\\Mendix\\ProcureFlowHub-AI_usage"
"""
import sys
import os
import sqlite3

def main():
    if len(sys.argv) < 2:
        print("Usage: python diagnose_mpr_v3.py <path to PROJECT FOLDER (not the .mpr file)>")
        sys.exit(1)

    project_path = sys.argv[1]
    mpr_path = None
    for entry in os.listdir(project_path):
        if entry.lower().endswith(".mpr"):
            mpr_path = os.path.join(project_path, entry)
            break

    if not mpr_path:
        print("No .mpr file found in that folder.")
        sys.exit(1)

    print(f"Using .mpr: {mpr_path}\n")

    conn = sqlite3.connect(mpr_path)
    cur = conn.cursor()

    # 1. Distinct ContainmentName values + counts
    cur.execute("""
        SELECT ContainmentName, COUNT(*) as cnt
        FROM Unit
        GROUP BY ContainmentName
        ORDER BY cnt DESC
        LIMIT 80
    """)
    rows = cur.fetchall()
    print(f"[1] Distinct ContainmentName values ({len(rows)} shown, sorted by frequency):")
    for name, cnt in rows:
        print(f"    {cnt:>5}  |  {name!r}")
    print()

    # 2. Grab a handful of sample hashes + their ContainmentName, to test resolution
    cur.execute("SELECT ContainmentName, ContentsHash FROM Unit WHERE ContentsHash IS NOT NULL AND ContentsHash != '' LIMIT 8")
    sample_hashes = cur.fetchall()
    conn.close()

    print(f"[2] Sample (ContainmentName, ContentsHash) pairs:")
    for cn, h in sample_hashes:
        print(f"    {cn!r:30} -> {h}")
    print()

    # 3. Explore mprcontents folder layout
    mprcontents_path = os.path.join(project_path, "mprcontents")
    print(f"[3] Exploring: {mprcontents_path}")
    if not os.path.isdir(mprcontents_path):
        print("    !! mprcontents folder not found at that path.")
        return

    top_entries = os.listdir(mprcontents_path)
    print(f"    Top-level entries ({len(top_entries)} total, showing up to 20):")
    for e in top_entries[:20]:
        full = os.path.join(mprcontents_path, e)
        kind = "DIR" if os.path.isdir(full) else "FILE"
        print(f"      [{kind}] {e}")
    print()

    # If top-level entries are directories (sharded storage), peek one level deeper
    first_dir = next((e for e in top_entries if os.path.isdir(os.path.join(mprcontents_path, e))), None)
    if first_dir:
        sub_path = os.path.join(mprcontents_path, first_dir)
        sub_entries = os.listdir(sub_path)
        print(f"    Peeking inside first subfolder '{first_dir}' ({len(sub_entries)} entries, showing up to 15):")
        for e in sub_entries[:15]:
            print(f"      {e}")
        print()

    # 4. Try to resolve one of the sample hashes to an actual file
    print("[4] Attempting to resolve sample hashes to real files...")
    for cn, h in sample_hashes:
        candidates_tried = []
        found_path = None

        # Try a few plausible naming schemes
        variants = [
            h,
            h.replace("/", "_").replace("+", "-"),
            h.replace("=", ""),
        ]
        for v in variants:
            # direct file at top level
            p1 = os.path.join(mprcontents_path, v)
            candidates_tried.append(p1)
            if os.path.isfile(p1):
                found_path = p1
                break
            # sharded by first 2 chars as subfolder
            if len(v) > 2:
                p2 = os.path.join(mprcontents_path, v[:2], v[2:])
                candidates_tried.append(p2)
                if os.path.isfile(p2):
                    found_path = p2
                    break

        if found_path:
            size = os.path.getsize(found_path)
            print(f"    ✅ FOUND for {cn!r}: {found_path}  ({size} bytes)")
        else:
            print(f"    ❌ Not resolved for {cn!r} (hash: {h[:20]}...). Tried {len(candidates_tried)} path shapes.")


if __name__ == "__main__":
    main()