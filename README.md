## v1
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

## v2
The controller has been updated to read switch configurations from the [configs/](./configs/)

Usage:
```bash
./controller_v2.py
```

You can modify the rules in genconfig.py, then run the script to generate configuration files for each switch:
```bash
./genconfig.py
```