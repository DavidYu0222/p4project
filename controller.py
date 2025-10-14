#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
import os
import sys
import time
from time import sleep
import grpc

# Import P4Runtime lib from parent utils dir (same style as tutorials)
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '../../utils/'))
import p4runtime_lib.bmv2
import p4runtime_lib.helper
from p4runtime_lib.error_utils import printGrpcError
from p4runtime_lib.switch import ShutdownAllSwitchConnections

"""
controller.py

Programs DSCP tagging rules on s21 and s22.
Tag mapping:
 - 192.168.11.0/24 -> A tag -> DSCP 10
 - 192.168.12.0/24 -> B tag -> DSCP 11
 - 192.168.13.0/24 -> C tag -> DSCP 12
"""

# Switch mapping: (grpc_addr, device_id)
TAG_SWITCH = {
    "s21": ("127.0.0.1:50054", 3),
    "s22": ("127.0.0.1:50055", 4)
}

FILTER_SWITCH = {
    "s11": ("127.0.0.1:50051", 0),
    "s12": ("127.0.0.1:50052", 1),
    "s13": ("127.0.0.1:50053", 2)
}

DSCP_A = 10   # Class A tag
DSCP_B = 11  # Class B tag
DSCP_C = 12  # Class C tag

TAG_P4INFO_FILE = "build/tag.p4.p4info.txtpb"
TAG_BMV2_JSON = "build/tag.json"

FILTER_P4INFO_FILE = "build/filter.p4.p4info.txtpb"
FILTER_BMV2_JSON = "build/filter.json"

def readTableRules(p4info_helper, sw):
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

def forwarding_rule(p4info_helper, sw, sw_name):
    print(f"[+] Start inserting forwarding rule to {sw_name}")

    try:
        ### Build table
        tbl_entries = []
        
        if sw_name == "s11":
            # s11 forward packet
            tname = "MyIngress.ipv4_lpm"
            forward_action_name = "MyIngress.ipv4_forward"
            drop_action_name = "MyIngress.drop"

            tbl_entries.append((
                tname,
                p4info_helper.buildTableEntry(
                    table_name=tname,
                    default_action=True,
                    action_name=drop_action_name,
                    action_params={}
                )
            ))
            tbl_entries.append((
                tname,
                p4info_helper.buildTableEntry(
                    table_name=tname,
                    match_fields={"hdr.ipv4.dstAddr": ("192.168.11.1", 32)},
                    action_name=forward_action_name,
                    action_params={"dstAddr": "08:00:00:00:01:11",
                                   "port": 1}
                )
            ))
            tbl_entries.append((
                tname,
                p4info_helper.buildTableEntry(
                    table_name=tname,
                    match_fields={"hdr.ipv4.dstAddr": ("192.168.11.2", 32)},
                    action_name=forward_action_name,
                    action_params={"dstAddr": "08:00:00:00:01:22",
                                   "port": 2}
                )
            ))
            tbl_entries.append((
                tname,
                p4info_helper.buildTableEntry(
                    table_name=tname,
                    match_fields={"hdr.ipv4.dstAddr": ("192.168.0.0", 16)},
                    action_name=forward_action_name,
                    action_params={"dstAddr": "08:00:00:00:04:00",
                                   "port": 3}
                )
            ))
        
        elif sw_name == "s12":
            # s11 forward packet
            tname = "MyIngress.ipv4_lpm"
            forward_action_name = "MyIngress.ipv4_forward"
            drop_action_name = "MyIngress.drop"

            tbl_entries.append((
                tname,
                p4info_helper.buildTableEntry(
                    table_name=tname,
                    default_action=True,
                    action_name=drop_action_name,
                    action_params={}
                )
            ))
            tbl_entries.append((
                tname,
                p4info_helper.buildTableEntry(
                    table_name=tname,
                    match_fields={"hdr.ipv4.dstAddr": ("192.168.12.1", 32)},
                    action_name=forward_action_name,
                    action_params={"dstAddr": "08:00:00:00:02:11",
                                   "port": 1}
                )
            ))
            tbl_entries.append((
                tname,
                p4info_helper.buildTableEntry(
                    table_name=tname,
                    match_fields={"hdr.ipv4.dstAddr": ("192.168.12.2", 32)},
                    action_name=forward_action_name,
                    action_params={"dstAddr": "08:00:00:00:02:22",
                                   "port": 2}
                )
            ))
            tbl_entries.append((
                tname,
                p4info_helper.buildTableEntry(
                    table_name=tname,
                    match_fields={"hdr.ipv4.dstAddr": ("192.168.0.0", 16)},
                    action_name=forward_action_name,
                    action_params={"dstAddr": "08:00:00:00:04:00",
                                   "port": 3}
                )
            ))
        
        elif sw_name == "s13":
            # s11 forward packet
            tname = "MyIngress.ipv4_lpm"
            forward_action_name = "MyIngress.ipv4_forward"
            drop_action_name = "MyIngress.drop"

            tbl_entries.append((
                tname,
                p4info_helper.buildTableEntry(
                    table_name=tname,
                    default_action=True,
                    action_name=drop_action_name,
                    action_params={}
                )
            ))
            tbl_entries.append((
                tname,
                p4info_helper.buildTableEntry(
                    table_name=tname,
                    match_fields={"hdr.ipv4.dstAddr": ("192.168.13.1", 32)},
                    action_name=forward_action_name,
                    action_params={"dstAddr": "08:00:00:00:03:11",
                                   "port": 1}
                )
            ))
            tbl_entries.append((
                tname,
                p4info_helper.buildTableEntry(
                    table_name=tname,
                    match_fields={"hdr.ipv4.dstAddr": ("192.168.13.2", 32)},
                    action_name=forward_action_name,
                    action_params={"dstAddr": "08:00:00:00:03:22",
                                   "port": 2}
                )
            ))
            tbl_entries.append((
                tname,
                p4info_helper.buildTableEntry(
                    table_name=tname,
                    match_fields={"hdr.ipv4.dstAddr": ("192.168.13.3", 32)},
                    action_name=forward_action_name,
                    action_params={"dstAddr": "08:00:00:00:03:33",
                                   "port": 3}
                )
            ))
            tbl_entries.append((
                tname,
                p4info_helper.buildTableEntry(
                    table_name=tname,
                    match_fields={"hdr.ipv4.dstAddr": ("192.168.0.0", 16)},
                    action_name=forward_action_name,
                    action_params={"dstAddr": "08:00:00:00:05:00",
                                   "port": 4}
                )
            ))

        elif sw_name == "s21":
            # s21 forward packet
            tname = "MyIngress.ipv4_lpm"
            forward_action_name = "MyIngress.ipv4_forward"
            drop_action_name = "MyIngress.drop"

            tbl_entries.append((
                tname,
                p4info_helper.buildTableEntry(
                    table_name=tname,
                    default_action=True,
                    action_name=drop_action_name,
                    action_params={}
                )
            ))
            tbl_entries.append((
                tname,
                p4info_helper.buildTableEntry(
                    table_name=tname,
                    match_fields={"hdr.ipv4.dstAddr": ("192.168.11.0", 24)},
                    action_name=forward_action_name,
                    action_params={"dstAddr": "08:00:00:00:01:00",
                                   "port": 1}
                )
            ))
            tbl_entries.append((
                tname,
                p4info_helper.buildTableEntry(
                    table_name=tname,
                    match_fields={"hdr.ipv4.dstAddr": ("192.168.12.0", 24)},
                    action_name=forward_action_name,
                    action_params={"dstAddr": "08:00:00:00:02:00",
                                   "port": 2}
                )
            ))
            tbl_entries.append((
                tname,
                p4info_helper.buildTableEntry(
                    table_name=tname,
                    match_fields={"hdr.ipv4.dstAddr": ("192.168.0.0", 16)},
                    action_name=forward_action_name,
                    action_params={"dstAddr": "08:00:00:00:05:00",
                                   "port": 3}
                )
            ))
        elif sw_name == "s22":
            tname = "MyIngress.ipv4_lpm"
            forward_action_name = "MyIngress.ipv4_forward"
            drop_action_name = "MyIngress.drop"

            tbl_entries.append((
                tname,
                p4info_helper.buildTableEntry(
                    table_name=tname,
                    default_action=True,
                    action_name=drop_action_name,
                    action_params={}
                )
            ))
            tbl_entries.append((
                tname,
                p4info_helper.buildTableEntry(
                    table_name=tname,
                    match_fields={"hdr.ipv4.dstAddr": ("192.168.13.0", 24)},
                    action_name=forward_action_name,
                    action_params={"dstAddr": "08:00:00:00:03:00",
                                   "port": 1}
                )
            ))
            tbl_entries.append((
                tname,
                p4info_helper.buildTableEntry(
                    table_name=tname,
                    match_fields={"hdr.ipv4.dstAddr": ("192.168.0.0", 16)},
                    action_name=forward_action_name,
                    action_params={"dstAddr": "08:00:00:00:04:00",
                                   "port": 2}
                )
            ))

        # Insert entries
        for (tname, entry) in tbl_entries:
            try:
                sw.WriteTableEntry(entry)
                print(f"    -> Inserted entry into table '{tname}' on {sw_name}")
            except Exception as e:
                print(f"    ! Failed to insert entry into '{tname}' on {sw_name}: {e}")
                # optionally print gRPC details
                if isinstance(e, grpc.RpcError):
                    printGrpcError(e)
                raise

    except Exception as e:
        print(f"[!] Error programming {sw_name}: {e}")
        # try best-effort shutdown of this switch connection
        try:
            sw.Shutdown()
        except Exception:
            pass
        raise

def tagging_rule(p4info_helper, sw, sw_name):
    print(f"[+] Start inserting tagging rule to {sw_name}")

    try:
        ### Build table
        tbl_entries = []

        if sw_name == "s21":
            # s21: tag 11 -> DSCP_A, 12 -> DSCP_B
            tname = "MyEgress.set_dscp_tag"
            aname = "MyEgress.modify_dscp"

            tbl_entries.append((
                tname,
                p4info_helper.buildTableEntry(
                    table_name=tname,
                    match_fields={"hdr.ipv4.srcAddr": ("192.168.11.0", 24)},
                    action_name=aname,
                    action_params={"dscp_value": DSCP_A}
                )
            ))
            tbl_entries.append((
                tname,
                p4info_helper.buildTableEntry(
                    table_name=tname,
                    match_fields={"hdr.ipv4.srcAddr": ("192.168.12.0", 24)},
                    action_name=aname,
                    action_params={"dscp_value": DSCP_B}
                )
            ))

        elif sw_name == "s22":
            # s22: tag 13 -> DSCP_C
            tname = "MyEgress.set_dscp_tag"
            aname = "MyEgress.modify_dscp"

            tbl_entries.append((
                tname,
                p4info_helper.buildTableEntry(
                    table_name=tname,
                    match_fields={"hdr.ipv4.srcAddr": ("192.168.13.0", 24)},
                    action_name=aname,
                    action_params={"dscp_value": DSCP_C}
                )
            ))

        # Insert entries
        for (tname, entry) in tbl_entries:
            try:
                sw.WriteTableEntry(entry)
                print(f"    -> Inserted entry into table '{tname}' on {sw_name}")
            except Exception as e:
                print(f"    ! Failed to insert entry into '{tname}' on {sw_name}: {e}")
                # optionally print gRPC details
                if isinstance(e, grpc.RpcError):
                    printGrpcError(e)
                raise

    except Exception as e:
        print(f"[!] Error programming {sw_name}: {e}")
        # try best-effort shutdown of this switch connection
        try:
            sw.Shutdown()
        except Exception:
            pass
        raise

def filter_rule(p4info_helper, sw, sw_name):
    print(f"[+] Start inserting filter rule to {sw_name}")

    try:
        ### Build table
        tbl_entries = []

        # if sw_name == "s11":
        #     # s11: tag 11 -> DSCP_A, 12 -> DSCP_B
        #     tname = "MyEgress.filter_dscp_tag"
        #     aname = "MyEgress.drop"

        #     tbl_entries.append((
        #         tname,
        #         p4info_helper.buildTableEntry(
        #             table_name=tname,
        #             match_fields={"hdr.ipv4.diffserv": (DSCP_C, 8)},
        #             action_name=aname,
        #             action_params={}
        #         )
        #     ))

        # elif sw_name == "s12":
        #     # s22: tag 13 -> DSCP_C
        #     tname = "MyEgress.filter_dscp_tag"
        #     aname = "MyEgress.drop"

        #     tbl_entries.append((
        #         tname,
        #         p4info_helper.buildTableEntry(
        #             table_name=tname,
        #             match_fields={"hdr.ipv4.diffserv": (DSCP_C, 8)},
        #             action_name=aname,
        #             action_params={}
        #         )
        #     ))

        # Insert entries
        for (tname, entry) in tbl_entries:
            try:
                sw.WriteTableEntry(entry)
                print(f"    -> Inserted entry into table '{tname}' on {sw_name}")
            except Exception as e:
                print(f"    ! Failed to insert entry into '{tname}' on {sw_name}: {e}")
                # optionally print gRPC details
                if isinstance(e, grpc.RpcError):
                    printGrpcError(e)
                raise

    except Exception as e:
        print(f"[!] Error programming {sw_name}: {e}")
        # try best-effort shutdown of this switch connection
        try:
            sw.Shutdown()
        except Exception:
            pass
        raise

def install_pipeline_and_rule(p4info_helper, sw_name, sw_addr, device_id):
    print(f"\n----- Connecting to {sw_name} @ {sw_addr} (device_id={device_id}) -----")
    proto_dump = f"logs/{sw_name}-p4runtime.txt"
    sw = p4runtime_lib.bmv2.Bmv2SwitchConnection(
        name=sw_name,
        address=sw_addr,
        device_id=device_id,
        proto_dump_file=proto_dump)

    # try to acquire mastership
    try:
        sw.MasterArbitrationUpdate()
    except Exception as e:
        print(f"    ! Master arbitration/update failed for {sw_name}: {e}")
        raise

    ## Install pipeline
    if sw_name in TAG_SWITCH:
        try:
            print(f"    -> Installing pipeline on {sw_name}")
            sw.SetForwardingPipelineConfig(
                p4info=p4info_helper.p4info,
                bmv2_json_file_path=TAG_BMV2_JSON)
        except grpc.RpcError as e:
            # If pipeline already installed or permission issues, just warn and continue
            print(f"    ! SetForwardingPipelineConfig warning for {sw_name}: {e.code().name} {getattr(e, 'details', lambda: '')()}")
            print("    ! Continuing (pipeline may already be installed).")
        
        forwarding_rule(p4info_helper, sw, sw_name)
        tagging_rule(p4info_helper, sw, sw_name)
    else:
        try:
            print(f"    -> Installing pipeline on {sw_name}")
            sw.SetForwardingPipelineConfig(
                p4info=p4info_helper.p4info,
                bmv2_json_file_path=FILTER_BMV2_JSON)
        except grpc.RpcError as e:
            # If pipeline already installed or permission issues, just warn and continue
            print(f"    ! SetForwardingPipelineConfig warning for {sw_name}: {e.code().name} {getattr(e, 'details', lambda: '')()}")
            print("    ! Continuing (pipeline may already be installed).")
        
        forwarding_rule(p4info_helper, sw, sw_name)
        filter_rule(p4info_helper, sw, sw_name)
    print(f"[+] {sw_name} programmed successfully.")
    return sw

def main():
    conns = []
    try:
        for sw_name, (addr, dev_id) in TAG_SWITCH.items():
            #sw = tagging_rule(p4info_helper, sw_name, addr, dev_id)
            p4info_helper = p4runtime_lib.helper.P4InfoHelper(TAG_P4INFO_FILE)
            sw = install_pipeline_and_rule(p4info_helper, sw_name, addr, dev_id)
            conns.append(sw)
            readTableRules(p4info_helper, sw)
        
        for sw_name, (addr, dev_id) in FILTER_SWITCH.items():
            #sw = tagging_rule(p4info_helper, sw_name, addr, dev_id)
            p4info_helper = p4runtime_lib.helper.P4InfoHelper(FILTER_P4INFO_FILE)
            sw = install_pipeline_and_rule(p4info_helper, sw_name, addr, dev_id)
            conns.append(sw)
            readTableRules(p4info_helper, sw)

        print("[+] Done programming")
    except KeyboardInterrupt:
        print("[!] Interrupted by user")
    finally:
        print("[+] Shutting down connections (global)...")
        ShutdownAllSwitchConnections()
        print("[+] Shutdown complete.")

if __name__ == "__main__":
    main()
