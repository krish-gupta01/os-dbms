"""Run after schema.sql to create demo accounts and storage nodes."""
import os
from werkzeug.security import generate_password_hash
from db import fetch_one, execute
from storage import init_storage

def main():
    for username, password, role in [
        ("admin", "admin123", "admin"),
        ("student", "student123", "user"),
    ]:
        if not fetch_one("SELECT user_id FROM users WHERE username=%s", (username,)):
            execute("INSERT INTO users(username,password_hash,role) VALUES(%s,%s,%s)",
                    (username, generate_password_hash(password), role))
    init_storage()

    # Register storage nodes. URLs are read from environment variables so the
    # same script works whether both PCs are on the same network or different networks.
    pc1_name = os.getenv("PC1_NODE_NAME", "pc-1-node")
    pc1_url = os.getenv("PC1_NODE_URL", "http://127.0.0.1:7001")
    pc1_path = os.getenv("PC1_STORAGE_DIR", "./node_storage_pc1")
    pc1_capacity = int(os.getenv("PC1_CAPACITY_MB", "10240")) * 1024 * 1024

    pc2_name = os.getenv("PC2_NODE_NAME", "pc-2-node")
    pc2_url = os.getenv("PC2_NODE_URL", "http://127.0.0.1:7002")
    pc2_path = os.getenv("PC2_STORAGE_DIR", "./node_storage_pc2")
    pc2_capacity = int(os.getenv("PC2_CAPACITY_MB", "10240")) * 1024 * 1024

    nodes = [
        (pc1_name, pc1_path, pc1_url, pc1_capacity),
        (pc2_name, pc2_path, pc2_url, pc2_capacity),
    ]
    for node_name, base_path, node_url, capacity in nodes:
        existing = fetch_one("SELECT node_id FROM storage_nodes WHERE node_name=%s", (node_name,))
        if not existing:
            execute("INSERT INTO storage_nodes(node_name,base_path,node_url,capacity_bytes,status) VALUES(%s,%s,%s,%s,'ONLINE')",
                    (node_name, base_path, node_url, capacity))
            print(f"Registered storage node: {node_name} at {node_url}")
        else:
            print(f"Storage node already exists: {node_name} (URL: {node_url})")
    init_storage()
    print("Seed complete. Demo accounts: admin/admin123 and student/student123")
    print(f"Storage nodes: {pc1_name} ({pc1_url}) and {pc2_name} ({pc2_url})")

if __name__ == "__main__":
    main()
