# ============================================================
# CROSS-NETWORK DEPLOYMENT GUIDE
# Distributed File Management System (DFMS)
# ============================================================

## Overview
- **PC-1** (Main Server): Runs MySQL, Flask app, and Node Agent 1
- **PC-2** (Storage Node): Runs only Node Agent 2
- Both PCs must be able to communicate over the network

## Required Ports
| Port | Service | PC | Purpose |
|------|---------|-----|---------|
| 3306 | MySQL | PC-1 | Database |
| 5000 | Flask | PC-1 | Web interface |
| 7001 | Node Agent | PC-1 | Storage node 1 |
| 7002 | Node Agent | PC-2 | Storage node 2 |

## Step 1: PC-1 Setup (Main Server)

### 1.1 Configure MySQL for Remote Access
Edit MySQL config (usually at `C:\Program Files\MySQL\MySQL Server 8.0\my.ini`):
```ini
[mysqld]
bind-address = 0.0.0.0
```
Restart MySQL service.

### 1.2 Create Remote User (Optional but Recommended)
```sql
CREATE USER 'dfms_user'@'%' IDENTIFIED BY 'your_password';
GRANT ALL PRIVILEGES ON dfms_db.* TO 'dfms_user'@'%';
FLUSH PRIVILEGES;
```

### 1.3 Forward Ports on PC-1's Router
- Port 3306 → PC-1 (MySQL)
- Port 5000 → PC-1 (Flask)
- Port 7001 → PC-1 (Node Agent)

### 1.4 Get PC-1's IP Address
```cmd
ipconfig
```
Note the IPv4 address (e.g., 192.168.1.10)

### 1.5 Configure .env on PC-1
Copy `.env.pc1.example` to `.env` and adjust:
- `DB_HOST=127.0.0.1` (local MySQL)
- `PC2_NODE_URL=http://<PC-2-IP>:7002` (PC-2's address)
- `NODE_SHARED_TOKEN=<same-token-on-both-PCs>`

### 1.6 Initialize Database
```cmd
# Run schema
mysql -u root -p < schema.sql

# Seed users and register nodes
python seed.py
```

### 1.7 Start Services on PC-1
```cmd
START_PC1.bat
```
Or manually:
```cmd
# Start node agent 1
python node_agent.py --name pc-1-node --storage-dir ./node_storage_pc1 --host 0.0.0.0 --port 7001

# Start main app
python app.py
```

## Step 2: PC-2 Setup (Remote Storage Node)

### 2.1 Forward Ports on PC-2's Router
- Port 7002 → PC-2 (Node Agent)

### 2.2 Get PC-2's IP Address
```cmd
ipconfig
```
Note the IPv4 address (e.g., 192.168.1.100)

### 2.3 Configure .env on PC-2
Copy `.env.pc2.example` to `.env` and adjust:
- `DB_HOST=<PC-1-IP>` (PC-1's address)
- `NODE_SHARED_TOKEN=<same-token-as-PC-1>`
- `NODE_AGENT_PORT=7002`

### 2.4 Start Node Agent on PC-2
```cmd
START_PC2.bat
```
Or manually:
```cmd
python node_agent.py --name pc-2-node --storage-dir ./node_storage_pc2 --host 0.0.0.0 --port 7002
```

## Step 3: Register PC-2 Node

After PC-2's node agent is running, go back to PC-1 and re-run:
```cmd
python seed.py
```
This registers PC-2's URL in the database so the main app knows where to send data.

## Step 4: Verify Setup

On PC-1, open browser to: `http://<PC-1-IP>:5000/admin`
- Login as admin/admin123
- Check "Storage nodes" section
- Both pc-1-node and pc-2-node should show as ONLINE

## Troubleshooting

### PC-2 can't connect to PC-1's MySQL
- Verify PC-1's MySQL is running: `netstat -ano | findstr :3306`
- Check router port forwarding for 3306
- Test from PC-2: `telnet <PC-1-IP> 3306`
- Verify MySQL user permissions

### PC-1 can't reach PC-2's node agent
- Verify PC-2's node agent is running: `netstat -ano | findstr :7002`
- Check router port forwarding for 7002 on PC-2
- Test from PC-1: `curl http://<PC-2-IP>:7002/health`
- Verify shared token matches

### Same LAN (No Port Forwarding)
If both PCs are on the same network (e.g., same Wi-Fi), use LAN IPs directly:
- PC-1: 192.168.1.10
- PC-2: 192.168.1.100
- No router port forwarding needed

### Different Networks (Internet Required)
- Use public IP addresses
- Forward ports on both routers
- Consider using a VPN or ngrok for easier setup