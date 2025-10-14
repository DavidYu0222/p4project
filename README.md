1. In your shell, run:
   ```bash
   make run
   ```
   This will:
   * compile `filter.p4`, and `tag.p4`
   * start the ex-topo in Mininet 
   * configure all hosts with the commands listed in
   [ex-topo/topology.json](./ex-topo/topology.json)

2. You should now see a Mininet command prompt. Try to ping between
   hosts in the topology:
   ```bash
   mininet> dump
   mininet> h1 ping h2
   mininet> pingall
   ```
3. Type `exit` to leave each xterm and the Mininet command line.
   Then, to stop mininet:
   ```bash
   make stop
   ```
   And to delete all pcaps, build files, and logs:
   ```bash
   make clean
   ```