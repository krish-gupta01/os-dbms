@echo off
REM Start both storage node agents (PC-1 on port 7001, PC-2 on port 7002)
REM Run this from the project directory.

echo Starting PC-1 node agent on port 7001...
start "PC-1 Node" /min python node_agent.py --name pc-1-node --storage-dir ./node_storage_pc1 --host 0.0.0.0 --port 7001

timeout /t 1 /nobreak > nul

echo Starting PC-2 node agent on port 7002...
start "PC-2 Node" /min python node_agent.py --name pc-2-node --storage-dir ./node_storage_pc2 --host 0.0.0.0 --port 7002

echo Both node agents started.
echo PC-1: http://127.0.0.1:7001
echo PC-2: http://127.0.0.1:7002