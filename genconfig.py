#!/usr/bin/env python3
"""
generate_configs.py

Generate per-switch JSON config files (configs/<sw>-config.json) based on the
hard-coded rules that were previously embedded in the controller script.

Files produced:
 - configs/s11-config.json
 - configs/s12-config.json
 - configs/s13-config.json
 - configs/s21-config.json
 - configs/s22-config.json

Adjust the constants below if you want different p4info / bmv2 json paths.
"""
import os
import json

# Output directory for per-switch configs
OUT_DIR = "configs"

# P4 artifacts (match the names used by your controller)
TAG_P4INFO_FILE = "build/tag.p4.p4info.txtpb"
TAG_BMV2_JSON = "build/tag.json"

FILTER_P4INFO_FILE = "build/filter.p4.p4info.txtpb"
FILTER_BMV2_JSON = "build/filter.json"

# fallback / basic p4 (for forwarding switches in your original script)
BASIC_P4INFO_FILE = "build/basic.p4.p4info.txtpb"
BASIC_BMV2_JSON = "build/basic.json"

# DSCP constants used in your controller
DSCP_A = 10   # Class A tag
DSCP_B = 11   # Class B tag
DSCP_C = 12   # Class C tag

# conveniently describe each switch's entries (mirrors your controller logic)
SWITCH_CONFIGS = {
    "s11": {
        "p4info": FILTER_P4INFO_FILE,
        "bmv2_json": FILTER_BMV2_JSON,
        "table_entries": [
            { "table": "MyIngress.ipv4_lpm", "default_action": True, "action_name": "MyIngress.drop", "action_params": {} },
            { "table": "MyIngress.ipv4_lpm", "match": { "hdr.ipv4.dstAddr": ["192.168.11.1", 32] }, "action_name": "MyIngress.ipv4_forward", "action_params": { "dstAddr": "08:00:00:00:01:11", "port": 1 } },
            { "table": "MyIngress.ipv4_lpm", "match": { "hdr.ipv4.dstAddr": ["192.168.11.2", 32] }, "action_name": "MyIngress.ipv4_forward", "action_params": { "dstAddr": "08:00:00:00:01:22", "port": 2 } },
            { "table": "MyIngress.ipv4_lpm", "match": { "hdr.ipv4.dstAddr": ["192.168.0.0", 16] }, "action_name": "MyIngress.ipv4_forward", "action_params": { "dstAddr": "08:00:00:00:04:00", "port": 3 } }
            { "table": "MyEgress.filter_dscp_tag", "match": { "hdr.ipv4.diffserv": [DSCP_C, 8] }, "action_name": "MyEgress.drop", "action_params": {} }
        ]
    },
    "s12": {
        "p4info": FILTER_P4INFO_FILE,
        "bmv2_json": FILTER_BMV2_JSON,
        "table_entries": [
            { "table": "MyIngress.ipv4_lpm", "default_action": True, "action_name": "MyIngress.drop", "action_params": {} },
            { "table": "MyIngress.ipv4_lpm", "match": { "hdr.ipv4.dstAddr": ["192.168.12.1", 32] }, "action_name": "MyIngress.ipv4_forward", "action_params": { "dstAddr": "08:00:00:00:02:11", "port": 1 } },
            { "table": "MyIngress.ipv4_lpm", "match": { "hdr.ipv4.dstAddr": ["192.168.12.2", 32] }, "action_name": "MyIngress.ipv4_forward", "action_params": { "dstAddr": "08:00:00:00:02:22", "port": 2 } },
            { "table": "MyIngress.ipv4_lpm", "match": { "hdr.ipv4.dstAddr": ["192.168.0.0", 16] }, "action_name": "MyIngress.ipv4_forward", "action_params": { "dstAddr": "08:00:00:00:04:00", "port": 3 } }
        ]
    },
    "s13": {
        "p4info": FILTER_P4INFO_FILE,
        "bmv2_json": FILTER_BMV2_JSON,
        "table_entries": [
            { "table": "MyIngress.ipv4_lpm", "default_action": True, "action_name": "MyIngress.drop", "action_params": {} },
            { "table": "MyIngress.ipv4_lpm", "match": { "hdr.ipv4.dstAddr": ["192.168.13.1", 32] }, "action_name": "MyIngress.ipv4_forward", "action_params": { "dstAddr": "08:00:00:00:03:11", "port": 1 } },
            { "table": "MyIngress.ipv4_lpm", "match": { "hdr.ipv4.dstAddr": ["192.168.13.2", 32] }, "action_name": "MyIngress.ipv4_forward", "action_params": { "dstAddr": "08:00:00:00:03:22", "port": 2 } },
            { "table": "MyIngress.ipv4_lpm", "match": { "hdr.ipv4.dstAddr": ["192.168.13.3", 32] }, "action_name": "MyIngress.ipv4_forward", "action_params": { "dstAddr": "08:00:00:00:03:33", "port": 3 } },
            { "table": "MyIngress.ipv4_lpm", "match": { "hdr.ipv4.dstAddr": ["192.168.0.0", 16] }, "action_name": "MyIngress.ipv4_forward", "action_params": { "dstAddr": "08:00:00:00:05:00", "port": 4 } }
        ]
    },
    "s21": {
        "p4info": TAG_P4INFO_FILE,
        "bmv2_json": TAG_BMV2_JSON,
        "table_entries": [
            { "table": "MyIngress.ipv4_lpm", "default_action": True, "action_name": "MyIngress.drop", "action_params": {} },
            { "table": "MyIngress.ipv4_lpm", "match": { "hdr.ipv4.dstAddr": ["192.168.11.0", 24] }, "action_name": "MyIngress.ipv4_forward", "action_params": { "dstAddr": "08:00:00:00:01:00", "port": 1 } },
            { "table": "MyIngress.ipv4_lpm", "match": { "hdr.ipv4.dstAddr": ["192.168.12.0", 24] }, "action_name": "MyIngress.ipv4_forward", "action_params": { "dstAddr": "08:00:00:00:02:00", "port": 2 } },
            { "table": "MyIngress.ipv4_lpm", "match": { "hdr.ipv4.dstAddr": ["192.168.0.0", 16] }, "action_name": "MyIngress.ipv4_forward", "action_params": { "dstAddr": "08:00:00:00:05:00", "port": 3 } },
            { "table": "MyEgress.set_dscp_tag", "match": { "hdr.ipv4.srcAddr": ["192.168.11.0", 24] }, "action_name": "MyEgress.modify_dscp", "action_params": { "dscp_value": DSCP_A } },
            { "table": "MyEgress.set_dscp_tag", "match": { "hdr.ipv4.srcAddr": ["192.168.12.0", 24] }, "action_name": "MyEgress.modify_dscp", "action_params": { "dscp_value": DSCP_B } }
        ]
    },
    "s22": {
        "p4info": TAG_P4INFO_FILE,
        "bmv2_json": TAG_BMV2_JSON,
        "table_entries": [
            { "table": "MyIngress.ipv4_lpm", "default_action": True, "action_name": "MyIngress.drop", "action_params": {} },
            { "table": "MyIngress.ipv4_lpm", "match": { "hdr.ipv4.dstAddr": ["192.168.13.0", 24] }, "action_name": "MyIngress.ipv4_forward", "action_params": { "dstAddr": "08:00:00:00:03:00", "port": 1 } },
            { "table": "MyIngress.ipv4_lpm", "match": { "hdr.ipv4.dstAddr": ["192.168.0.0", 16] }, "action_name": "MyIngress.ipv4_forward", "action_params": { "dstAddr": "08:00:00:00:04:00", "port": 2 } }
            { "table": "MyEgress.set_dscp_tag", "match": { "hdr.ipv4.srcAddr": ["192.168.13.0", 24] }, "action_name": "MyEgress.modify_dscp", "action_params": { "dscp_value": DSCP_C } }
        ]
    },
    # optionally add others...
}

def ensure_out_dir():
    if not os.path.exists(OUT_DIR):
        os.makedirs(OUT_DIR)

def write_configs():
    ensure_out_dir()
    for sw_name, cfg in SWITCH_CONFIGS.items():
        out_path = os.path.join(OUT_DIR, f"{sw_name}-config.json")
        with open(out_path, 'w') as f:
            json.dump(cfg, f, indent=2)
        print(f"Wrote {out_path}")

if __name__ == "__main__":
    write_configs()
    print("All configs written to ./configs/ - review them before running the controller.")
