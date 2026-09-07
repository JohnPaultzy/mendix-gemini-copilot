"""
Standalone diagnostic for the Domain Model parser.
Run from the mendix-copilot project root (same folder as app.py):

    python diagnose_mpr.py "C:\\Users\\Owner\\Mendix\\ProcureFlowHub-AI_usage\\App.mpr"

This does NOT modify anything. It just reports what the parser is actually
seeing inside your .mpr file so we can pinpoint why zero entities were found.
"""
import sys
import sqlite3
import re

from core.mendix_parser import extract_all_strings_from_blob, _auto_discover_module_names_from_text

def main():
    if len(sys.argv) < 2:
        print("Usage: python diagnose_mpr.py <path to App.mpr>")
        sys.exit(1)

    mpr_path = sys.argv[1]
    print(f"Opening: {mpr_path}\n")

    conn = sqlite3.connect(mpr_path)
    cur = conn.cursor()

    # 1. What tables exist?
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cur.fetchall()]
    print(f"[1] Tables found in the SQLite DB ({len(tables)}):")
    print("    " + ", ".join(tables[:40]))
    print()

    if "_Unit" not in tables:
        print("!! No '_Unit' table found — this .mpr uses a different internal schema than expected.")
        print("   Full table list above; please share it so the query can be adapted.")
        conn.close()
        return

    # 2. How many rows total, and how many match our DomainModel filter?
    cur.execute("SELECT COUNT(*) FROM _Unit")
    total_rows = cur.fetchone()[0]
    print(f"[2] Total rows in _Unit: {total_rows}")

    cur.execute("SELECT COUNT(*) FROM _Unit WHERE _Type LIKE '%DomainModel%' OR _Type LIKE '%Entities%'")
    dm_rows = cur.fetchone()[0]
    print(f"    Rows matching DomainModel/Entities filter: {dm_rows}")
    print()

    # 3. Sample of distinct _Type values (helps confirm actual naming convention used)
    cur.execute("SELECT DISTINCT _Type FROM _Unit LIMIT 60")
    types = [r[0] for r in cur.fetchall()]
    print(f"[3] Sample of distinct _Type values ({len(types)} shown, may be truncated):")
    for t in types:
        print(f"    - {t}")
    print()

    # 4. Pull whatever rows we'd actually use (DomainModel filter, else fallback to all non-null _Contents)
    if dm_rows > 0:
        cur.execute("SELECT _Contents FROM _Unit WHERE _Type LIKE '%DomainModel%' OR _Type LIKE '%Entities%'")
    else:
        print("    (No DomainModel-typed rows — falling back to ALL non-null _Contents rows, like the app does)")
        cur.execute("SELECT _Contents FROM _Unit WHERE _Contents IS NOT NULL")
    rows = cur.fetchall()
    conn.close()

    print(f"[4] Rows fetched for text extraction: {len(rows)}")

    domain_dump_strings = []
    for row in rows:
        if isinstance(row[0], bytes):
            domain_dump_strings.extend(extract_all_strings_from_blob(row[0]))
    domain_text = " ".join(domain_dump_strings)
    print(f"    Total decoded text length: {len(domain_text)} characters")
    print()

    # 5. Try the same auto-discovery the app uses
    candidates = _auto_discover_module_names_from_text(domain_text)
    print(f"[5] Auto-discovered candidate module names ({len(candidates)}):")
    print("    " + (", ".join(candidates[:60]) if candidates else "(none found)"))
    print()

    # 6. Raw peek: does the word 'DomainModel' or 'Entity' or 'Association' even appear anywhere?
    for kw in ["DomainModel", "Entity", "Association", "AttributeType"]:
        count = domain_text.count(kw)
        print(f"[6] Occurrences of '{kw}' in decoded text: {count}")
    print()

    # 7. Show a small raw snippet so we can eyeball the actual text shape
    print("[7] First 800 characters of decoded text (sanity check):")
    print("-" * 70)
    print(domain_text[:800])
    print("-" * 70)


if __name__ == "__main__":
    main()