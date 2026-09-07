"""
Diagnostic v9 — dumps the COMPLETE, untruncated CrossAssociations entries
from ProcureFlow's DomainModel, so we can see their exact field shape
(likely different from regular Associations, e.g. possibly referencing the
foreign entity by qualified NAME string rather than a resolvable GUID).

Run from the project root:
    python diagnose_mpr_v9.py "C:\\Users\\Owner\\Mendix\\ProcureFlowHub-AI_usage"
"""
import sys
import os
import sqlite3
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.mendix_parser import _find_project_mpr_file, _load_mxunit_dict


def to_jsonable(obj):
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, bytes):
        return f"<bytes len={len(obj)}>"
    return obj


def main():
    if len(sys.argv) < 2:
        print("Usage: python diagnose_mpr_v9.py <path to PROJECT FOLDER>")
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

    cross_assocs = procureflow_dm.get('CrossAssociations', []) or []
    print(f"[*] CrossAssociations list has {len(cross_assocs)} raw items (including the usual leading marker).\n")

    for i, item in enumerate(cross_assocs):
        print(f"--- item[{i}] ---")
        if isinstance(item, dict):
            print(json.dumps(to_jsonable(item), indent=2, default=str))
        else:
            print(f"NON-DICT -> {item!r}")
        print()


if __name__ == "__main__":
    main()