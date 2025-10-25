#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
controller.py - config-driven P4Runtime controller with PostgreSQL tag/filter integration

Install order per switch:
  1) pipeline (bmv2 json)
  2) forwarding rules from configs/<sw>-config.json (table_entries)
  3) tag rules from DB (tag_table) -> write MyEgress.set_dscp_tag entries
  4) filter rules from DB (filter_table) -> write MyEgress.filter_dscp_tag entries

Usage:
  - Put config files under ./configs/ such as configs/s11-config.json
  - Ensure PostgreSQL (tag_table/filter_table) is reachable
  - Start BMv2 switches, then run:
      python3 controller.py
"""
import os
import sys
import time
import json
import grpc
from time import sleep
import hashlib

import psycopg2
import psycopg2.extras

# helper path used by the tutorials repo
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             '../../utils/'))
import p4runtime_lib.bmv2
import p4runtime_lib.helper
from p4runtime_lib.error_utils import printGrpcError
from p4runtime_lib.switch import ShutdownAllSwitchConnections

from p4.v1 import p4runtime_pb2

# --- Adjust these to suit your layout ---
CONFIG_DIR = "configs"   # per-switch JSON files live here: e.g. configs/s11-config.json
POLL_INTERVAL = 10

TAG_SWITCH = {
    "s21": ("127.0.0.1:50055", 4),
    "s22": ("127.0.0.1:50056", 5),
    "s23": ("127.0.0.1:50057", 6),
    "s24": ("127.0.0.1:50058", 7)
}
FILTER_SWITCH = {
    "s11": ("127.0.0.1:50051", 0),
    "s12": ("127.0.0.1:50052", 1),
    "s13": ("127.0.0.1:50053", 2),
    "s14": ("127.0.0.1:50054", 3)
}

# set this if you used the other names
DEFAULT_P4INFO = "build/basic.p4.p4info.txtpb"
DEFAULT_BMV2_JSON = "build/basic.json"

DB_HOST = "127.0.0.1"
DB_PORT = 5432
DB_USER = "p4"
DB_PASSWORD = "p4pass"
DB_NAME = "p4controller"


# ---------------- DB operation --------------------

def get_db_conn():
    """Return a new psycopg2 connection (throws on error)."""
    return psycopg2.connect(host=DB_HOST, port=DB_PORT, dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD)


def fetch_tag_rules(conn, switch_name):
    """
    Return list of dicts: { 'id': int, 'match': <dict_or_none>, 'tag_value': int }
    match is the JSONB stored in tag_table (e.g. {"hdr.ipv4.srcAddr": ["192.168.11.0",24]})
    """
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT id, match, tag_value FROM tag_table WHERE switch_name=%s ORDER BY id", (switch_name,))
        return cur.fetchall()


def fetch_filter_rules(conn, switch_name):
    """
    Return list of dicts: { 'id': int, 'tag_value': int }
    """
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT id, tag_value FROM filter_table WHERE switch_name=%s ORDER BY id", (switch_name,))
        return cur.fetchall()


def compute_db_hash(conn, switch_name):
    """
    Compute an md5 fingerprint based on tag_table and filter_table rows for the switch.
    If DB error occurs, raises exception.
    """
    parts = []
    with conn.cursor() as cur:
        # tag_table rows
        cur.execute("SELECT id, match::text, tag_value FROM tag_table WHERE switch_name=%s ORDER BY id", (switch_name,))
        for r in cur.fetchall():
            # r = (id, match_text, tag_value)
            parts.append(f"TAG:{r[0]}:{r[1] or ''}:{r[2]}")

        # filter_table rows
        cur.execute("SELECT id, tag_value FROM filter_table WHERE switch_name=%s ORDER BY id", (switch_name,))
        for r in cur.fetchall():
            parts.append(f"FILT:{r[0]}:{r[1]}")

    combined = "|".join(parts)
    return hashlib.md5(combined.encode()).hexdigest()


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
    """
    if raw is None:
        return None
    # if already list/tuple convert to tuple
    if isinstance(raw, (list, tuple)):
        if len(raw) == 1:
            return (raw[0],)
        return tuple(raw)
    # if it's a string or number, coerce into a one- or two-element tuple
    if isinstance(raw, str):
        return (raw,)
    if isinstance(raw, int):
        return (raw, 0)
    return raw


def build_entry_from_json(p4info_helper, entry_obj):
    """
    Convert a JSON description into a p4runtime table entry (using p4info_helper.buildTableEntry).
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


def delete_all_db_managed_entries(sw, p4info_helper):
    """
    Read all table entries from the switch and delete entries that belong to
    MyEgress.set_dscp_tag or MyEgress.filter_dscp_tag.
    """
    tables_to_remove = {"MyEgress.set_dscp_tag", "MyEgress.filter_dscp_tag"}
    print(f"    -> Deleting existing DB-managed entries on {sw.name} ...")
    try:
        for response in sw.ReadTableEntries():
            for entity in response.entities:
                entry = entity.table_entry
                # resolve table name
                try:
                    table_name = p4info_helper.get_tables_name(entry.table_id)
                except Exception:
                    table_name = None
                # remove entries in table
                if table_name in tables_to_remove:
                    try:
                        request = p4runtime_pb2.WriteRequest()
                        request.device_id = sw.device_id
                        request.election_id.low = 1
                        update = request.updates.add()
                        update.type = p4runtime_pb2.Update.DELETE
                        update.entity.table_entry.CopyFrom(entry)
                        sw.client_stub.Write(request)
                        print(f"      -> Deleted entry from {table_name} on {sw.name}")
                    except Exception as e:
                        print(f"      ! Failed to delete entry from {table_name} on {sw.name}: {e}")
                        if isinstance(e, grpc.RpcError):
                            printGrpcError(e)
                        # continue deleting other entries
    except Exception as e:
        print(f"    ! Error while reading table entries from {sw.name} for deletion: {e}")
        if isinstance(e, grpc.RpcError):
            printGrpcError(e)


def program_db_rules(db_conn, sw, p4info_helper):
    """
    Read tag_table and filter_table for switch sw_name and program corresponding
    rules to the switch. Install tag rules first, then filter rules.
    Tag rules use table MyEgress.set_dscp_tag with action MyEgress.modify_dscp(dscp_value).
    Filter rules use table MyEgress.filter_dscp_tag with action MyEgress.drop().
    """
    if db_conn is None:
        print(f"    -> No DB connection; skipping DB rules for {sw.name}")
        return

    delete_all_db_managed_entries(sw, p4info_helper)
    
    try:
        # TAG rules
        tag_rows = fetch_tag_rules(db_conn, sw.name)
        if tag_rows:
            tbl_entries = []
            for r in tag_rows:
                match = r.get('match') or {}
                tag_value = r.get('tag_value')
                # build a JSON-like record compatible with build_entry_from_json
                rec = {
                    'table': 'MyEgress.set_dscp_tag',
                    'match': match,
                    'action_name': 'MyEgress.modify_dscp',
                    'action_params': {'dscp_value': tag_value}
                }
                try:
                    tname, tentry = build_entry_from_json(p4info_helper, rec)
                    tbl_entries.append((tname, tentry))
                except Exception as ex:
                    print(f"    ! Error building tag entry for {sw.name} row {r.get('id')}: {ex}")
                    raise
            if tbl_entries:
                print(f"    -> Writing {len(tbl_entries)} tag entries (DB) to {sw.name}")
                write_entries(sw, tbl_entries)
        else:
            print(f"    -> No tag rules in DB for {sw.name}")

        # FILTER rules
        filter_rows = fetch_filter_rules(db_conn, sw.name)
        if filter_rows:
            tbl_entries = []
            for r in filter_rows:
                tag_value = r.get('tag_value')
                # match on hdr.ipv4.diffserv exact 8-bit match -> represent as [value, 8]
                rec = {
                    'table': 'MyEgress.filter_dscp_tag',
                    'match': {'hdr.ipv4.diffserv': [tag_value, 8]},
                    'action_name': 'MyEgress.drop',
                    'action_params': {}
                }
                try:
                    tname, tentry = build_entry_from_json(p4info_helper, rec)
                    tbl_entries.append((tname, tentry))
                except Exception as ex:
                    print(f"    ! Error building filter entry for {sw.name} row {r.get('id')}: {ex}")
                    raise
            if tbl_entries:
                print(f"    -> Writing {len(tbl_entries)} filter entries (DB) to {sw.name}")
                write_entries(sw, tbl_entries)
        else:
            print(f"    -> No filter rules in DB for {sw.name}")

    except Exception as e:
        print(f"    ! Error while programming DB rules for {sw.name}: {e}")
        if isinstance(e, grpc.RpcError):
            printGrpcError(e)
        raise


def program_from_config(sw_name, sw_addr, device_id, db_conn=None):
    """
    Load config for sw_name and program the switch accordingly.
    After config-based forwarding rules are written, read DB rules (tag/filter) and program them.
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
        p4info_path = cfg.get('p4info', DEFAULT_P4INFO)
        bmv2_json = cfg.get('bmv2_json', DEFAULT_BMV2_JSON)
        entries = cfg.get('table_entries', [])
        p4info_helper = p4runtime_lib.helper.P4InfoHelper(p4info_path)

        # install pipeline if bmv2_json is provided
        if bmv2_json:
            set_pipeline(sw, p4info_helper, bmv2_json)

        # build table entries (forwarding rules from config)
        tbl_entries = []
        for entry in entries:
            try:
                tname, tentry = build_entry_from_json(p4info_helper, entry)
                tbl_entries.append((tname, tentry))
            except Exception as ex:
                print(f"    ! Error building table entry from JSON: {ex}")
                raise

        # write forwarding entries first
        if tbl_entries:
            print(f"    -> Writing {len(tbl_entries)} forwarding entries (config) to {sw_name}")
            write_entries(sw, tbl_entries)
        else:
            print(f"    -> No table entries found in {sw_name}-config.json")
    else:
        # FALLBACK: old behavior: still need a p4info_helper for DB rules
        print(f"    ! Error no config file for {sw_name} (Not Found: {sw_name}-config.json)")
        raise

    # Now apply DB rules (tagging/filtering) AFTER forwarding rules are installed
    if db_conn:
        try:
            program_db_rules(db_conn, sw, p4info_helper)
        except Exception as e:
            print(f"    ! Failed to program DB rules for {sw_name}: {e}")
            # continue (do not abort overall)
    else:
        print(f"    -> No DB connection available; skipping DB-sourced tag/filter rules for {sw_name}")

    # Return the switch connection and the p4info helper used
    return sw, p4info_helper


# Refer tutorial/exercise/p4runtime/mycontroller.py
def read_table_rules(p4info_helper, sw):
    """
    Reads the table entries from all tables on the switch.
    """
    print('\n----- Reading tables rules for %s -----' % sw.name)
    for response in sw.ReadTableEntries():
        for entity in response.entities:
            entry = entity.table_entry
            try:
                table_name = p4info_helper.get_tables_name(entry.table_id)
            except Exception:
                table_name = f"<table id {entry.table_id}>"
            print('%s: ' % table_name, end=' ')
            for m in entry.match:
                try:
                    print(p4info_helper.get_match_field_name(table_name, m.field_id), end=' ')
                    print('%r' % (p4info_helper.get_match_field_value(m),), end=' ')
                except Exception:
                    print(f"<match field id {m.field_id}> ", end='')
            action = entry.action.action
            try:
                action_name = p4info_helper.get_actions_name(action.action_id)
            except Exception:
                action_name = f"<action id {action.action_id}>"
            print('->', action_name, end=' ')
            for p in action.params:
                try:
                    print(p4info_helper.get_action_param_name(action_name, p.param_id), end=' ')
                    print('%r' % p.value, end=' ')
                except Exception:
                    print(f"<param id {p.param_id} {repr(p.value)}> ", end='')
            print()


def printCounter(p4info_helper, sw, counter_name, index):
    """
    Reads the specified counter at the specified index from the switch. In our
    program, the index is the tunnel ID. If the index is 0, it will return all
    values from the counter.

    :param p4info_helper: the P4Info helper
    :param sw:  the switch connection
    :param counter_name: the name of the counter from the P4 program
    :param index: the counter index (in our case, the tunnel ID)
    """
    for response in sw.ReadCounters(p4info_helper.get_counters_id(counter_name), index):
        for entity in response.entities:
            counter = entity.counter_entry
            print("%s %s %d: %d packets" % (
                sw.name, counter_name, index,
                counter.data.packet_count
            ))

# ---------------- main ----------------
def main():
    all_conns = {}
    db_conn = None
    try:
        # try connect to DB once
        try:
            db_conn = get_db_conn()
            print(f"[+] Connected to DB")
        except Exception as e:
            print(f"[!] Could not connect to DB (will still program configs): {e}")
            db_conn = None

        # assemble the list of switches to program
        switches = {}
        switches.update(FILTER_SWITCH)
        switches.update(TAG_SWITCH)

        for sw_name, (addr, dev_id) in switches.items():
            try:
                sw_conn, p4info_helper = program_from_config(sw_name, addr, dev_id, db_conn)
                h = compute_db_hash(db_conn, sw_name)
                all_conns[sw_name] = {'sw_conn': sw_conn, 'p4info_helper': p4info_helper, 'hash': h}
                
                # read back tables
                read_table_rules(p4info_helper, sw_conn)
            except Exception as e:
                print(f"[!] Error during programming of {sw_name}: {e}")
                # continue (do not abort all)

        # print("[+] Done programming all switches.")
        print("[+] Initial programming complete. Entering watch loop (poll DB). Press Ctrl-C to stop.")

        while True:
            print(f"[+] Start Detect")
            # ensure DB connection alive
            if db_conn is None:
                try:
                    db_conn = get_db_conn()
                    print("[+] Reconnected to DB")
                except Exception:
                    # still not available; skip this round
                    time.sleep(POLL_INTERVAL)
                    continue

            # for each programmed switch, compute new fingerprint and compare
            for sw_name, sw_info in list(all_conns.items()):
                try:
                    new_h = compute_db_hash(db_conn, sw_name)
                except Exception as e:
                    print(f"    ! Error computing fingerprint for {sw_name}: {e}")
                    new_h = None

                sw_conn = sw_info.get('sw_conn')
                p4info_helper = sw_info.get('p4info_helper')
                old_h = sw_info.get('hash')

                if new_h != old_h:
                    print(f"[-] Detected DB change for {sw_name} (old={old_h} new={new_h})")
                    
                    try:
                        program_db_rules(db_conn, sw_conn, p4info_helper)
                    except Exception as e:
                        print(f"    ! Failed to program DB rules for {sw_name}: {e}")
                        # continue (do not abort overall)
                        continue
                    print(f"[-] Successfully apply new rule for {sw_name}")
                    all_conns[sw_name] = {'sw_conn': sw_conn, 'p4info_helper': p4info_helper, 'hash': new_h}
                else:
                    # no change
                    print(f"[-] No rule change for {sw_name}")
                    pass

                if sw_conn.name in TAG_SWITCH:
                    printCounter(p4info_helper, sw_conn, "tag_counter", 0)
                else:
                    printCounter(p4info_helper, sw_conn, "filter_counter", 0)

            print(f"[+] End Detect")

                


            time.sleep(POLL_INTERVAL)
            
            
    except KeyboardInterrupt:
        print("[!] Interrupted by user")
    finally:
        db_conn.close()
        print("[+] Shutting down connections (global)...")
        ShutdownAllSwitchConnections()
        print("[+] Shutdown complete.")


if __name__ == "__main__":
    main()
