## Prerequisites

### Install P4 development tools
Follow the official [P4 Tutorial Guide](https://github.com/jafingerhut/p4-guide/blob/master/bin/README-install-troubleshooting.md) to install the P4 development environment or the provided P4 VM.
> We use the P4 VM (2025/02/01) on VirtualBox.

### Install Docker
Follow the official [Docker installation guide](https://docs.docker.com/engine/install/ubuntu/) to install the Docker Engine.
> we use 28.5.1.

Add the **p4** user to the Docker group:
```bash
sudo usermod -aG docker $USER
newgrp docker
```

### Install psycopg2 for Python
Activate the P4 virtual environment and install the PostgreSQL adapter
```bash
(p4dev-python-venv) $ pip install psycopg2-binary
```

## Running Steps:

### Clone the project
```bash
cd ~/tutorials/exercises
git clone https://github.com/DavidYu0222/p4project.git
cd p4project
```

### Run DB container
Start the PostgreSQL container:
```bash
docker compose up -d
```

Check if the tables exist:
```bash
docker exec -it p4-postgres psql -U p4 -d p4controller
```

Inside **psql**:
```psql
\dt
```

Expected output:
```bash
           List of relations
 Schema |     Name     | Type  | Owner 
--------+--------------+-------+-------
 public | filter_table | table | p4
 public | switches     | table | p4
 public | tag_table    | table | p4
(3 rows)
```

Some SQL to modify table:
```sql
SELECT * FROM filter_table;

INSERT INTO filter_table (switch_name, tag_value) VALUES ('s12', 13);

DELETE FROM filter_table WHERE id = <rule_id>;
```

### Run mininet
Start the P4 topology:
```bash
make run
```

If you want to modify initial flow rules, you can:
1. Edit configuration files directly under [./configs/](./configs/)
```bash
vim ./configs/sx-config.json
```

2. Regenerate all config files using the script:
```bash
vim ./genconfigs.py
./genconfigs.py
```

### Run controller to install flow rule
In a new terminal:
```bash
./controller_db.py
```
After initial setup for each switch, controller will enter monitor mode to periodically check the database every POLL_INTERVAL (default: 10 seconds) and apply any detected changes to the switches. Press Ctrl+C to leave.

> If an error occurs, ensure the BMv2 switch gRPC ports match those defined in your config files.

### Test in Mininet
Inside the Mininet CLI:
```cli
dump
pingall
h11 ping h41
h11 xterm
```

## Changelog

### v1
1. In your shell, run:
   ```bash
   make run
   ```
   This will:
   * compile `filter.p4`, and `tag.p4`
   * start the ex-topo in Mininet 
   * configure all hosts with the commands listed in
   [ex-topo/topology.json](./ex-topo/topology.json)

2. In the new shell, run:
   ```bash
   ./controller.py
   ```
   This will:
   * install the pipeline and flow rules on the switches in Mininet
   * note that all flow rules are hardcoded in the script

3. You should now see a Mininet command prompt. Try to ping between
   hosts in the topology:
   ```bash
   mininet> dump
   mininet> h1 ping h2
   mininet> pingall
   ```
4. Type `exit` to leave each xterm and the Mininet command line.
   Then, to stop mininet:
   ```bash
   make stop
   ```
   And to delete all pcaps, build files, and logs:
   ```bash
   make clean
   ```

---

### v2
This version updates the controller to read switch configurations from JSON files under the [./configs/](./configs/)

Usage:
```bash
./controller_v2.py
```

To modify rules, edit genconfig.py, then regenerate configuration files:
```bash
./genconfig.py
```

---

### v3
This version integrates the controller with PostgreSQL 17, running in a Docker container.
Flow rules are now dynamically loaded from the database.

Usage:
```bash
./controller_db.py
```

The previous version (v2) is still available:
Usage:
```bash
./controller.py
```

### v4
This version of the controller periodically checks the database every POLL_INTERVAL (default: 10 seconds) and applies any detected changes to the switches.
It also retrieves and displays the counters for tagged and filtered packets in the terminal.

Usage:
```bash
./controller_db.py
```