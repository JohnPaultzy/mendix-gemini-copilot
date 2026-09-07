"""
Diagnostic v2 — inspects the real 'Unit' table schema (columns) and samples
its content, since this .mpr uses 'Unit' instead of '_Unit'.

Run:
    python diagnose_mpr_v2.py "C:\\Users\\Owner\\Mendix\\ProcureFlowHub-AI_usage\\App.mpr"
"""
import sys
import sqlite3

def main():
    if len(sys.argv) < 2:
        print("Usage: python diagnose_mpr_v2.py <path to App.mpr>")
        sys.exit(1)

    mpr_path = sys.argv[1]
    print(f"Opening: {mpr_path}\n")

    conn = sqlite3.connect(mpr_path)
    cur = conn.cursor()

    # 1. Column names/types of the Unit table
    cur.execute("PRAGMA table_info(Unit)")
    cols = cur.fetchall()
    print(f"[1] Columns in 'Unit' table ({len(cols)}):")
    for c in cols:
        # c = (cid, name, type, notnull, dflt_value, pk)
        print(f"    - {c[1]}  (type: {c[2]})")
    print()

    col_names = [c[1] for c in cols]

    # 2. Row count
    cur.execute("SELECT COUNT(*) FROM Unit")
    total = cur.fetchone()[0]
    print(f"[2] Total rows in Unit: {total}\n")

    # 3. Try to guess which column holds the "type" info and which holds the blob content
    type_like_cols = [c for c in col_names if 'type' in c.lower()]
    content_like_cols = [c for c in col_names if any(k in c.lower() for k in ['content', 'data', 'blob', 'value'])]
    print(f"[3] Columns that look like a 'type' column: {type_like_cols}")
    print(f"    Columns that look like a 'content/data' column: {content_like_cols}\n")

    # 4. Sample 5 full rows (raw) so we can see actual shapes/values
    cur.execute(f"SELECT * FROM Unit LIMIT 5")
    sample_rows = cur.fetchall()
    print(f"[4] Sample rows (first 5), one column at a time:")
    for i, row in enumerate(sample_rows):
        print(f"  -- Row {i} --")
        for cname, val in zip(col_names, row):
            if isinstance(val, bytes):
                print(f"    {cname}: <bytes, length={len(val)}>")
            else:
                val_str = str(val)
                if len(val_str) > 150:
                    val_str = val_str[:150] + "...(truncated)"
                print(f"    {cname}: {val_str}")
    print()

    # 5. If we found a plausible "type" column, show distinct values
    if type_like_cols:
        tcol = type_like_cols[0]
        cur.execute(f"SELECT DISTINCT {tcol} FROM Unit LIMIT 60")
        distinct_types = [r[0] for r in cur.fetchall()]
        print(f"[5] Distinct values in '{tcol}' ({len(distinct_types)} shown):")
        for t in distinct_types:
            print(f"    - {t}")

    conn.close()


if __name__ == "__main__":
    main()