-- rebuild_schema.sql
-- Recreate switches, tag_table, filter_table according to requested schema.
-- WARNING: This drops the existing tables and all their data. Run only if you intend to replace existing data.
BEGIN;

-- Drop old tables if present (drop in dependency order)
DROP TABLE IF EXISTS filter_table;
DROP TABLE IF EXISTS tag_table;
DROP TABLE IF EXISTS switches;

-- Create switches table
CREATE TABLE IF NOT EXISTS switches (
  name TEXT PRIMARY KEY,
  ip TEXT NOT NULL,
  deviceID INT NOT NULL
);

-- Create tag_table: rules to apply tags (matching JSONB)
CREATE TABLE IF NOT EXISTS tag_table (
  id SERIAL PRIMARY KEY,
  switch_name TEXT NOT NULL REFERENCES switches(name) ON DELETE CASCADE,
  match JSONB,         -- e.g. {"hdr.ipv4.srcAddr":["192.168.11.0",24]}
  tag_value INT        -- DSCP or tag code to set
);

-- Create filter_table: rules to filter by tag_value (e.g. drop if matches)
CREATE TABLE IF NOT EXISTS filter_table (
  id SERIAL PRIMARY KEY,
  switch_name TEXT NOT NULL REFERENCES switches(name) ON DELETE CASCADE,
  tag_value INT        -- tag value to filter (drop)
);

-- Indexes for faster lookup
CREATE INDEX IF NOT EXISTS idx_tag_table_switch ON tag_table(switch_name);
CREATE INDEX IF NOT EXISTS idx_filter_table_switch ON filter_table(switch_name);
-- GIN index for JSONB 'match' to allow JSON containment queries
CREATE INDEX IF NOT EXISTS idx_tag_table_match_gin ON tag_table USING GIN (match jsonb_path_ops);

-- Example switch entries (adjust IPs & deviceIDs as needed)
INSERT INTO switches (name, ip, deviceID) VALUES
  ('s11', '127.0.0.1:50051', 0),
  ('s12', '127.0.0.1:50052', 1),
  ('s13', '127.0.0.1:50053', 2),
  ('s14', '127.0.0.1:50054', 3),
  ('s21', '127.0.0.1:50055', 4),
  ('s22', '127.0.0.1:50056', 5),
  ('s23', '127.0.0.1:50057', 6),
  ('s24', '127.0.0.1:50058', 7)
ON CONFLICT (name) DO NOTHING;

-- Example tag rules (tag_table)
-- s21 tags traffic with src 192.168.11.0/24 as DSCP 10, src 192.168.12.0/24 as DSCP 11
INSERT INTO tag_table (switch_name, match, tag_value) VALUES
  ('s21', '{"hdr.ipv4.srcAddr":["192.168.11.0",24]}'::jsonb, 10),
  ('s21', '{"hdr.ipv4.srcAddr":["192.168.12.0",24]}'::jsonb, 11),
  ('s22', '{"hdr.ipv4.srcAddr":["192.168.13.0",24]}'::jsonb, 12),
  ('s23', '{"hdr.ipv4.srcAddr":["192.168.13.0",24]}'::jsonb, 12),
  ('s24', '{"hdr.ipv4.srcAddr":["192.168.14.0",24]}'::jsonb, 13);
  

-- Example filter rules (filter_table)
-- s11 will drop packets with tag_value 12
INSERT INTO filter_table (switch_name, tag_value) VALUES
  ('s11', 12);

COMMIT;
