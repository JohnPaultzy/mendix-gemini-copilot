"""
Diagnostic v8 — dumps the COMPLETE, untruncated 'PurchaseRequest' entity BSON
dict (no depth/list limits this time) and recursively searches every string
value in it for 'Requester' / 'Approver' / 'BestCandidate', to find out
definitively where (or whether) those labels actually live in the data.

Run from the project root:
    python diagnose_mpr_v8.py "C:\\Users\\Owner\\Mendix\\ProcureFlowHub-AI_usage"
"""
import sys
import os
import sqlite3
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.mendix_parser import _find_project_mpr_file, _load_mxunit_dict


def find_matches(obj, needles, path=""):
    """Recursively search obj for any string containing one of the needles."""
    hits = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            hits.extend(find_matches(v, needles, f"{path}.{k}"))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            hits.extend(find_matches(v, needles, f"{path}[{i}]"))
    elif isinstance(obj, str):
        for n in needles:
            if n.lower() in obj.lower():
                hits.append((path, obj))
                break
    return hits


def to_jsonable(obj):
    """Make the dict JSON-serializable (bytes -> length marker) for a full dump."""
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, bytes):
        return f"<bytes len={len(obj)}>"
    return obj


def main():
    if len(sys.argv) < 2:
        print("Usage: python diagnose_mpr_v8.py <path to PROJECT FOLDER>")
        sys.exit(1)

    project_path = sys.argv[1]
    mpr_path = _find_project_mpr_file(project_path)
    if not mpr_path:
        print("No .mpr found.")
        sys.exit(1)

    mprcontents_path = os.path.join(project_path, "mprcontents")

    conn = sqlite3.connect(mpr_path)
    cur = conn.cursor()
    cur.execute("SELECT UnitID, ContainerID, ContainmentName FROM Unit WHERE ContainmentName IN ('Modules', 'DomainModel')")
    rows = cur.fetchall()
    conn.close()

    module_unit_ids = set()
    domainmodel_rows = []
    for unit_id, container_id, cn in rows:
        if cn == 'Modules':
            module_unit_ids.add(bytes(unit_id))
        elif cn == 'DomainModel':
            domainmodel_rows.append((bytes(unit_id), bytes(container_id)))

    # Find ProcureFlow's DomainModel dict specifically
    procureflow_dm = None
    for dm_unit_id, dm_container_id in domainmodel_rows:
        if dm_container_id not in module_unit_ids:
            continue
        module_dict = _load_mxunit_dict(mprcontents_path, dm_container_id)
        if module_dict and module_dict.get('Name') == 'ProcureFlow':
            procureflow_dm = _load_mxunit_dict(mprcontents_path, dm_unit_id)
            break

    if not procureflow_dm:
        print("Could not find ProcureFlow's DomainModel unit.")
        return

    # Find the PurchaseRequest entity specifically
    purchase_request = None
    for item in procureflow_dm.get('Entities', []) or []:
        if isinstance(item, dict) and item.get('Name') == 'PurchaseRequest':
            purchase_request = item
            break

    if not purchase_request:
        print("Could not find the PurchaseRequest entity.")
        return

    print("[*] Searching PurchaseRequest's FULL entity dict for 'Requester'/'Approver'/'BestCandidate'...\n")
    hits = find_matches(purchase_request, ["Requester", "Approver", "BestCandidate"])
    if hits:
        print(f"[*] Found {len(hits)} matching field(s):")
        for path, val in hits:
            print(f"    {path} = {val!r}")
    else:
        print("[*] NO matches found anywhere in PurchaseRequest's entity dict.")
    print()

    # Also search the ENTIRE ProcureFlow DomainModel dict (all entities + associations)
    print("[*] Searching the FULL ProcureFlow DomainModel dict (all entities + associations)...\n")
    hits2 = find_matches(procureflow_dm, ["Requester", "Approver", "BestCandidate"])
    if hits2:
        print(f"[*] Found {len(hits2)} matching field(s) project-wide in ProcureFlow's DomainModel:")
        for path, val in hits2[:40]:
            print(f"    {path} = {val!r}")
        if len(hits2) > 40:
            print(f"    ... ({len(hits2) - 40} more)")
    else:
        print("[*] NO matches found ANYWHERE in ProcureFlow's entire DomainModel dict.")
    print()

    # Dump the full untruncated PurchaseRequest entity as JSON to a file for inspection
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "purchase_request_full_dump.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(to_jsonable(purchase_request), f, indent=2, default=str)
    print(f"[*] Full untruncated PurchaseRequest entity dumped to: {out_path}")
    print("    (Feel free to open/share this file if the searches above found nothing.)")


if __name__ == "__main__":
    main()