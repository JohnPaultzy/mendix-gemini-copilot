"""
Diagnostic v7 — uses the REAL production parser functions (imported from
core.mendix_parser) to:
  1. Find the ProcureFlow module's DomainModel unit and print its COMPLETE
     raw Associations list (every field, unfiltered) so we can see exactly
     what's there for Requester/Approver/BestCandidate.
  2. Build the same global entity-GUID map the app builds (across ALL 26
     modules) and check whether each association's Parent/ChildPointer
     actually resolves — and if not, say why.

Run from the mendix-copilot project root:
    python diagnose_mpr_v7.py "C:\\Users\\Owner\\Mendix\\ProcureFlowHub-AI_usage"
"""
import sys
import os
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.mendix_parser import (
    _find_project_mpr_file, _load_mxunit_dict, _extract_entities_and_raw_associations
)


def main():
    if len(sys.argv) < 2:
        print("Usage: python diagnose_mpr_v7.py <path to PROJECT FOLDER>")
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

    print(f"[*] Found {len(module_unit_ids)} Module units and {len(domainmodel_rows)} DomainModel units total.\n")

    # Build the SAME global entity map the real app builds, across ALL modules.
    global_entity_map = {}   # guid -> (module_name, entity_name)
    module_dm_dicts = {}     # module_name -> dm_dict (kept so we can re-inspect ProcureFlow's raw list)
    unresolved_module_count = 0

    for dm_unit_id, dm_container_id in domainmodel_rows:
        if dm_container_id not in module_unit_ids:
            unresolved_module_count += 1
            continue
        module_dict = _load_mxunit_dict(mprcontents_path, dm_container_id)
        module_name = module_dict.get('Name') if module_dict else None
        if not module_name:
            unresolved_module_count += 1
            continue
        dm_dict = _load_mxunit_dict(mprcontents_path, dm_unit_id)
        if not dm_dict:
            continue
        entities, raw_associations, local_map = _extract_entities_and_raw_associations(dm_dict)
        for guid, name in local_map.items():
            global_entity_map[guid] = (module_name, name)
        module_dm_dicts[module_name] = (dm_dict, raw_associations)

    print(f"[*] Global entity map built: {len(global_entity_map)} entities total across all resolvable modules.")
    print(f"    (DomainModel units skipped due to unresolved owning module: {unresolved_module_count})\n")

    if "ProcureFlow" not in module_dm_dicts:
        print("!! 'ProcureFlow' module not found among parsed modules. Available modules:")
        print("   " + ", ".join(sorted(set(m for m, _ in global_entity_map.values()))))
        return

    dm_dict, raw_associations = module_dm_dicts["ProcureFlow"]

    print(f"[*] ProcureFlow DomainModel: {len(raw_associations)} raw associations found (via ParentPointer/ChildPointer/Name/Type).\n")
    print("=" * 100)
    for i, (parent_guid, child_guid, a_name, a_type) in enumerate(raw_associations):
        parent_info = global_entity_map.get(parent_guid)
        child_info = global_entity_map.get(child_guid)
        status = "OK" if (parent_info and child_info) else "!! UNRESOLVED"
        print(f"[{i}] Name={a_name!r}  Type={a_type!r}  STATUS={status}")
        print(f"     ParentPointer={parent_guid}  -> resolves to: {parent_info}")
        print(f"     ChildPointer ={child_guid}  -> resolves to: {child_info}")
        print()

    # Also do a raw, unfiltered dump of the Associations key directly from the
    # decoded dict, in case some items are being skipped by our dict-only filter
    # (e.g. an association shaped differently than we expect).
    print("=" * 100)
    print("[*] RAW dm_dict['Associations'] entries (unfiltered, showing $Type of every list item):")
    for i, item in enumerate(dm_dict.get('Associations', []) or []):
        if isinstance(item, dict):
            print(f"  item[{i}]: dict, $Type={item.get('$Type')!r}, Name={item.get('Name')!r}")
        else:
            print(f"  item[{i}]: NON-DICT -> {item!r}")


if __name__ == "__main__":
    main()