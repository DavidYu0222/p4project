#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
controller.py - config-driven P4Runtime controller

Reads per-switch JSON configs named "<sw_name>-config.json" from CONFIG_DIR and programs
the switch accordingly. Falls back to hard-coded behavior when no config file exists.

Usage:
  - Put config files under ./configs/ such as configs/s11-config.json
  - Run the script after the BMv2 switches are up:
      python3 controller.py
"""
import os
import sys
import time
import json
import grpc
from time import sleep

# helper path used by the tutorials repo
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             '../../utils/'))
import p4runtime_lib.bmv2
import p4runtime_lib.helper
from p4runtime_lib.error_utils import printGrpcError
from p4runtime_lib.switch import ShutdownAllSwitchConnections

# --- Adjust these to suit your layout ---
CONFIG_DIR = "configs"   # per-switch JSON files live here: e.g. configs/s11-config.json

# legacy defaults (kept for fallback behavior)
TAG_SWITCH = {
    "s21": ("127.0.0.1:50054", 3),
    "s22": ("127.0.0.1:50055", 4)
}
FILTER_SWITCH = {
    "s11": ("127.0.0.1:50051", 0),
    "s12": ("127.0.0.1:50052", 1),
    "s13": ("127.0.0.1:50053", 2)
}

# default p4 artifacts (used when config doesn't specify paths)
DEFAULT_TAG_P4INFO = "build/tag.p4.p4info.txtpb"
DEFAULT_TAG_BMV2_JSON = "build/tag.json"
DEFAULT_FILTER_P4INFO = "build/filter.p4.p4info.txtpb"
DEFAULT_FILTER_BMV2_JSON = "build/filter.json"

# set this if you used the other names
DEFAULT_P4INFO = "build/basic.p4.p4info.txtpb"
DEFAULT_BMV2_JSON = "build/basic.json"


# ---------------- helper utilities ----------------
def load_switch_config(sw_name):
    """
    Load <CONFIG_DIR>/<sw_name>-config.json if present.
    Returns a dict or None if not found.
    """
    path = os.path.join(CONFIG_DIR, f"{sw_name}-config.json")
    if not os.path.exists(path):
        return None
    with open(path, 'r') as f:
        return json.load(f)


def normalize_match_value(raw):
    """
    Normalize match value shapes to what p4runtime helper expects.

    Acceptable input shapes:
      - ["192.168.11.0", 24] -> returns ("192.168.11.0", 24)
      - ["0x0c", 8] or [12, 8] -> returns (12, 8)
      - "192.168.11.1" (string alone) -> returns ("192.168.11.1",)  (single-element; helper accepts)
      - 12 (int) -> returns (12, 0)   (helper will index value[0] and value[1])
    """
    # if already list/tuple convert to tuple
    if isinstance(raw, (list, tuple)):
        if len(raw) == 1:
            return (raw[0],)
        return tuple(raw)
    # if it's a string or number, coerce into a one- or two-element tuple
    if isinstance(raw, str):
        # single-element tuple; helper will be passed ("a.b.c.d",)
        return (raw,)
    if isinstance(raw, int):
        # fallback: (value, 0) - caller should prefer two-element form for LPM
        return (raw, 0)
    # unknown: return as-is to trigger a helpful error downstream
    return raw


def build_entry_from_json(p4info_helper, entry_obj):
    """
    Convert a JSON description into a p4runtime table entry (using p4info_helper.buildTableEntry).
    
    Supported JSON fields (per entry):
      - table (string) [required]
      - default_action (bool) [optional]
      - match (dict) [optional] : match field name -> value (see normalize_match_value)
      - action_name (string) [required for non-default]
      - action_params (dict) [optional]
    Returns a (table_name, table_entry) tuple.
    """
    if 'table' not in entry_obj:
        raise ValueError("table entry missing 'table' field")

    table_name = entry_obj['table']

    # default action case
    if entry_obj.get('default_action', False):
        action_name = entry_obj.get('action_name')
        action_params = entry_obj.get('action_params', {}) or {}
        entry = p4info_helper.buildTableEntry(
            table_name=table_name,
            default_action=True,
            action_name=action_name,
            action_params=action_params
        )
        return table_name, entry

    # normal entry with match fields
    match_fields = {}
    if 'match' in entry_obj and isinstance(entry_obj['match'], dict):
        for k, v in entry_obj['match'].items():
            match_fields[k] = normalize_match_value(v)

    action_name = entry_obj.get('action_name')
    action_params = entry_obj.get('action_params', {}) or {}

    table_entry = p4info_helper.buildTableEntry(
        table_name=table_name,
        match_fields=match_fields,
        action_name=action_name,
        action_params=action_params
    )
    return table_name, table_entry


# ---------------- core programming functions ----------------
def set_pipeline(sw, p4info_helper, bmv2_json_path):
    """
    Try to install the forwarding pipeline. If permission denied or pipeline already set,
    warn and continue.
    """
    try:
        print(f"    -> Installing pipeline (JSON: {bmv2_json_path}) on {sw.name}")
        sw.SetForwardingPipelineConfig(
            p4info=p4info_helper.p4info,
            bmv2_json_file_path=bmv2_json_path)
    except grpc.RpcError as e:
        # tolerate already-installed pipelines
        print(f"    ! SetForwardingPipelineConfig warning for {sw.name}: {getattr(e, 'code', lambda: '')()} {getattr(e, 'details', lambda: '')()}")
        print("    ! Continuing (pipeline may already be installed).")


def write_entries(sw, tbl_entries):
    """
    Write a list of (table_name, entry) tuples to switch sw.
    """
    for (tname, entry) in tbl_entries:
        try:
            sw.WriteTableEntry(entry)
            print(f"    -> Inserted entry into table '{tname}' on {sw.name}")
        except Exception as e:
            print(f"    ! Failed to insert entry into '{tname}' on {sw.name}: {e}")
            if isinstance(e, grpc.RpcError):
                printGrpcError(e)
            raise


def program_from_config(sw_name, sw_addr, device_id):
    """
    Load config for sw_name and program the switch accordingly.
    """
    print(f"\n----- Connecting to {sw_name} @ {sw_addr} (device_id={device_id}) -----")
    proto_dump = f"logs/{sw_name}-p4runtime.txt"
    sw = p4runtime_lib.bmv2.Bmv2SwitchConnection(
        name=sw_name,
        address=sw_addr,
        device_id=device_id,
        proto_dump_file=proto_dump)

    # acquire mastership
    try:
        sw.MasterArbitrationUpdate()
    except Exception as e:
        print(f"    ! Master arbitration/update failed for {sw_name}: {e}")
        raise

    # try to find config JSON for this switch
    cfg = load_switch_config(sw_name)
    # choose p4info helper and bmv2_json path from either config or defaults
    if cfg:
        p4info_path = cfg.get('p4info', cfg.get('p4Info', DEFAULT_P4INFO))
        bmv2_json = cfg.get('bmv2_json', cfg.get('bmv2_json', DEFAULT_BMV2_JSON))
        entries = cfg.get('table_entries', cfg.get('tableEntries', []))
        p4info_helper = p4runtime_lib.helper.P4InfoHelper(p4info_path)
        # install pipeline if bmv2_json is provided
        if bmv2_json:
            set_pipeline(sw, p4info_helper, bmv2_json)
        # build table entries
        tbl_entries = []
        for e in entries:
            try:
                tname, tentry = build_entry_from_json(p4info_helper, e)
                tbl_entries.append((tname, tentry))
            except Exception as ex:
                print(f"    ! Error building table entry from JSON: {ex}")
                raise
        # write entries
        if tbl_entries:
            print(f"    -> Writing {len(tbl_entries)} table entries to {sw_name}")
            write_entries(sw, tbl_entries)
        else:
            print(f"    -> No table entries found in {sw_name}-config.json")
    else:
        # FALLBACK: old behavior (keeps existing logic so you can migrate)
        print(f"    -> No config file for {sw_name}; using legacy hard-coded programming")
        
    # Return the switch connection to allow later ReadTableEntries
    return sw, p4info_helper


# Refer p4runtime/mycontroller.py
def read_table_rules(p4info_helper, sw):
    """
    Reads the table entries from all tables on the switch.

    :param p4info_helper: the P4Info helper
    :param sw: the switch connection
    """
    print('\n----- Reading tables rules for %s -----' % sw.name)
    for response in sw.ReadTableEntries():
        for entity in response.entities:
            entry = entity.table_entry
            # TODO For extra credit, you can use the p4info_helper to translate
            #      the IDs in the entry to names
            table_name = p4info_helper.get_tables_name(entry.table_id)
            print('%s: ' % table_name, end=' ')
            for m in entry.match:
                print(p4info_helper.get_match_field_name(table_name, m.field_id), end=' ')
                print('%r' % (p4info_helper.get_match_field_value(m),), end=' ')
            action = entry.action.action
            action_name = p4info_helper.get_actions_name(action.action_id)
            print('->', action_name, end=' ')
            for p in action.params:
                print(p4info_helper.get_action_param_name(action_name, p.param_id), end=' ')
                print('%r' % p.value, end=' ')
            print()


# ---------------- main ----------------
def main():
    all_conns = []
    try:
        # assemble the list of switches to program:
        # union of TAG_SWITCH and FILTER_SWITCH keys (you can also provide a custom list)
        switches = {}
        switches.update(TAG_SWITCH)
        switches.update(FILTER_SWITCH)

        for sw_name, (addr, dev_id) in switches.items():
            try:
                sw_conn, p4info_helper = program_from_config(sw_name, addr, dev_id)
                all_conns.append(sw_conn)
                # read back tables using the same p4info helper used for programming
                read_table_rules(p4info_helper, sw_conn)
            except Exception as e:
                print(f"[!] Error during programming of {sw_name}: {e}")
                # continue to the next switch (do not abort all)
                continue

        print("[+] Done programming all switches.")
    except KeyboardInterrupt:
        print("[!] Interrupted by user")
    finally:
        print("[+] Shutting down connections (global)...")
        ShutdownAllSwitchConnections()
        print("[+] Shutdown complete.")


if __name__ == "__main__":
    main()
