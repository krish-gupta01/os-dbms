# Distributed File Management System (OS + DBMS)

A Flask + MySQL teaching project demonstrating chunked distributed storage, per-chunk replication, integrity checks, reconstruction, video playback, access control, request scheduling, node failure simulation and audit logging. It supports both legacy local-folder nodes and physical storage PCs through an authenticated storage-node API.


- User registration/login and admin dashboard.
- Upload arbitrary files including large video files (default upload cap 1 GB; configure `MAX_UPLOAD_MB`).
- Split each file into fixed-size binary chunks (default 4 MiB, configurable with `CHUNK_SIZE_MB`).
- Place each chunk on `REPLICATION_FACTOR` distinct online nodes; MySQL stores chunk indexes, sizes, SHA-256 checksums and replica paths.
- Reconstruct downloads by retrieving one valid replica per chunk in index order, verifying each chunk and the complete original checksum.
- Play detected video files in a browser using a route that reconstructs the file and serves it with HTTP range support.
- Node status controls, chunk health report, replica repair, priority/FCFS scheduler views, file sharing and audit logs.


- Python 3.10+ (tested syntax-compatible with Python 3.13)
- MySQL Server 8.x
- VS Code or another terminal


1. Extract this folder and open it in VS Code.
2. Create a virtual environment and install dependencies:
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```
3. Copy `.env.example` to `.env` and set your real MySQL password. Keep `DB_NAME=dfms_db`.
4. Execute the complete `schema.sql` against MySQL. From PowerShell, if MySQL is installed in the default location:
   ```powershell
   Get-Content .\schema.sql | & "C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe" -u root -p
   ```
   This script creates the database and all base and chunk tables. If tables already exist, the `CREATE TABLE IF NOT EXISTS` statements are safe to rerun.
5. Seed demo accounts and storage nodes:
   ```powershell
   .\.venv\Scripts\python.exe seed.py
   ```
6. Start the server:
   ```powershell
   .\.venv\Scripts\python.exe app.py
   ```
7. Open `http://127.0.0.1:5000/login`. For LAN access, set `FLASK_HOST=0.0.0.0` and browse to `http://<PC-1-IP>:5000`.

## Demo accounts
- Admin: `admin` / `admin123`
- User: `student` / `student123`
Change these credentials before using the application outside a local demo.

## How chunk recovery works
1. Upload bytes are read in `CHUNK_SIZE_MB` blocks.
2. Each chunk receives an index and SHA-256 checksum and a row in `file_chunks`.
3. Each chunk is copied to distinct online nodes. A node can be a legacy local folder or a remote PC running `node_agent.py`; locations and health are tracked in `chunk_replicas`.
4. Download/play reads chunks in `chunk_index` order, selects an online healthy replica, checks size and checksum, and writes the bytes into a temporary reconstructed file. The final size and original file SHA-256 are checked before serving.
5. If a replica is missing/corrupt, another healthy copy is attempted. Admin repair can create replacement replicas when a valid source exists.

## OS and DBMS concepts demonstrated
- OS: priority scheduling and FCFS display, storage-resource allocation, node availability, replication, integrity verification, failure recovery and temporary-file I/O.
- DBMS: relational metadata, primary/foreign keys, uniqueness constraints, indexed request queue, transactions through the database helper, access permissions and audit records.

## Two-PC setup

Use PC-1 as the coordinator (this Flask app and MySQL) and PC-2 as a remote storage node. Both PCs must be on the same LAN/Wi-Fi. Do not use `localhost` or `127.0.0.1` as the remote node address.

1. On the existing coordinator database, run `migration_remote_nodes.sql` once. Fresh installs already receive these columns from `schema.sql`.
2. Copy the project folder, or at minimum `node_agent.py`, `.env`, and the required Python packages, to PC-2.
3. On PC-2 set these values in `.env` (the token must exactly match PC-1):
   ```env
   NODE_SHARED_TOKEN=a-long-random-shared-secret
   NODE_NAME=pc-2-node
   NODE_STORAGE_DIR=D:\DFMS\node2
   NODE_AGENT_HOST=0.0.0.0
   NODE_AGENT_PORT=7001
   ```
4. Start the remote agent on PC-2:
   ```powershell
   python node_agent.py
   ```
5. Find PC-2's LAN IPv4 address with `ipconfig`, for example `192.168.1.11`. Allow inbound TCP port `7001` in Windows Firewall and verify from PC-1 with `ping 192.168.1.11`.
6. Sign in to PC-1 as `admin` and open **Admin**. In **Storage nodes**, add:
   - Node name: `pc-2-node`
   - Remote URL: `http://192.168.1.11:7001`
   - Storage path / label: `D:\DFMS\node2`
   - Capacity: the amount you want the metadata scheduler to consider.
7. Click **Add & verify node**. The coordinator checks `/health` and `/stats`; use **Check connection** later to refresh status and storage usage.

Set `REPLICATION_FACTOR=2` when you want each chunk on both PCs. With `REPLICATION_FACTOR=1`, chunks are distributed round-robin across online nodes but one node failure can make some chunks unavailable.

## Important limitations
- The coordinator/MySQL instance is still a single point of failure; remote storage replication does not make the coordinator highly available.
- Video playback reconstructs the full video into a temporary file before serving; this is appropriate for a student demo but not efficient true streaming for very large media.
- If you have existing files uploaded with the older whole-file-replica version, upload them again after installing this version; old uploads have no chunk metadata.
- Use only files you are authorized to store.
