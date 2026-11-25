import os, time, uuid
from functools import wraps
from pathlib import Path
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file, abort, Response
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from db import fetch_all, fetch_one, execute, transaction
from scheduler import priority_schedule, fcfs_schedule
from storage import init_storage, store_chunked_file, reconstruct_file, repair_chunk_replicas, chunk_health, sha256_file, TEMP_ROOT

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "development-only-change-me")
MAX_BYTES = int(os.getenv("MAX_UPLOAD_MB", "1024")) * 1024 * 1024
FACTOR = max(1, int(os.getenv("REPLICATION_FACTOR", "2")))
app.config["MAX_CONTENT_LENGTH"] = MAX_BYTES
init_storage()

def log_action(user_id, action, details=""):
    execute("INSERT INTO audit_logs(user_id,action,details) VALUES(%s,%s,%s)", (user_id, action, details[:6000]))

def user_now():
    if not session.get("user_id"):
        return None
    return fetch_one("SELECT user_id,username,role FROM users WHERE user_id=%s", (session["user_id"],))

def login_required(fn):
    @wraps(fn)
    def inner(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return inner

def can_access(file_row, user, write=False):
    if user["role"] == "admin" or int(file_row["owner_id"]) == int(user["user_id"]):
        return True
    p = fetch_one("SELECT can_read,can_write FROM file_permissions WHERE file_id=%s AND user_id=%s",
                  (file_row["file_id"], user["user_id"]))
    return bool(p and (p["can_write"] if write else p["can_read"]))

def create_request(user_id, operation, priority=5, file_id=None, details=""):
    request_id, _ = execute("""INSERT INTO file_requests(user_id,file_id,operation,priority,status,details)
        VALUES(%s,%s,%s,%s,'QUEUED',%s)""", (user_id, file_id, operation, priority, details))
    return request_id

@app.context_processor
def inject_user():
    return {"logged_user": user_now()}

@app.route("/")
def index():
    return redirect(url_for("dashboard") if session.get("user_id") else url_for("login"))

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if len(username) < 3 or len(password) < 6:
            flash("Username must have at least 3 characters and password at least 6.", "danger")
        elif fetch_one("SELECT user_id FROM users WHERE username=%s", (username,)):
            flash("Username already exists.", "danger")
        else:
            execute("INSERT INTO users(username,password_hash,role) VALUES(%s,%s,'user')",
                    (username, generate_password_hash(password)))
            flash("Account created. Please sign in.", "success")
            return redirect(url_for("login"))
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        row = fetch_one("SELECT * FROM users WHERE username=%s", (username,))
        if row and check_password_hash(row["password_hash"], request.form.get("password", "")):
            session.clear()
            session["user_id"] = row["user_id"]
            log_action(row["user_id"], "LOGIN", "Successful login")
            return redirect(url_for("dashboard"))
        flash("Invalid username or password.", "danger")
    return render_template("login.html")

@app.route("/logout")
def logout():
    if session.get("user_id"):
        log_action(session["user_id"], "LOGOUT", "User logged out")
    session.clear()
    return redirect(url_for("login"))

@app.route("/dashboard")
@login_required
def dashboard():
    user = user_now()
    if user["role"] == "admin":
        files = fetch_all("""SELECT f.*,u.username owner_name,
            (SELECT COUNT(DISTINCT cr.node_id) FROM file_chunks ch JOIN chunk_replicas cr ON cr.chunk_id=ch.chunk_id WHERE ch.file_id=f.file_id AND cr.replica_status='HEALTHY') replica_count
            FROM files f JOIN users u ON u.user_id=f.owner_id WHERE f.deleted=0 ORDER BY f.created_at DESC""")
    else:
        files = fetch_all("""SELECT DISTINCT f.*,u.username owner_name,
            (SELECT COUNT(DISTINCT cr.node_id) FROM file_chunks ch JOIN chunk_replicas cr ON cr.chunk_id=ch.chunk_id WHERE ch.file_id=f.file_id AND cr.replica_status='HEALTHY') replica_count
            FROM files f JOIN users u ON u.user_id=f.owner_id
            LEFT JOIN file_permissions p ON p.file_id=f.file_id
            WHERE f.deleted=0 AND (f.owner_id=%s OR p.user_id=%s) ORDER BY f.created_at DESC""",
            (user["user_id"], user["user_id"]))
    stats = {
        "files": fetch_one("SELECT COUNT(*) n FROM files WHERE deleted=0")["n"],
        "users": fetch_one("SELECT COUNT(*) n FROM users")["n"],
        "replicas": fetch_one("SELECT COUNT(*) n FROM chunk_replicas WHERE replica_status='HEALTHY'")["n"],
        "nodes": fetch_one("SELECT COUNT(*) n FROM storage_nodes WHERE status='ONLINE'")["n"],
        "queued": fetch_one("SELECT COUNT(*) n FROM file_requests WHERE status='QUEUED'")["n"],
    }
    nodes = fetch_all("SELECT * FROM storage_nodes ORDER BY node_id")
    return render_template("dashboard.html", files=files, stats=stats, nodes=nodes)

@app.route("/upload", methods=["POST"])
@login_required
def upload():
    user = user_now()
    f = request.files.get("file")
    if not f or not f.filename:
        flash("Choose a file first.", "danger")
        return redirect(url_for("dashboard"))
    original = secure_filename(f.filename)
    if not original:
        flash("Invalid filename.", "danger")
        return redirect(url_for("dashboard"))
    temp = TEMP_ROOT / f"{uuid.uuid4().hex}_{original}"
    try:
        f.save(temp)
        size = temp.stat().st_size
        digest = sha256_file(temp)
        stored = f"{uuid.uuid4().hex}_{original}"
        request_id = create_request(user["user_id"], "UPLOAD", int(request.form.get("priority", "5")), None, original)
        execute("UPDATE file_requests SET status='PROCESSING' WHERE request_id=%s", (request_id,))
        file_id, _ = execute("""INSERT INTO files(owner_id,original_name,stored_name,size_bytes,sha256,content_type)
            VALUES(%s,%s,%s,%s,%s,%s)""",
            (user["user_id"], original, stored, size, digest, f.mimetype))
        try:
            store_chunked_file(file_id, str(temp), FACTOR)
            execute("UPDATE file_requests SET file_id=%s,status='COMPLETED',completed_at=NOW() WHERE request_id=%s",
                    (file_id, request_id))
            log_action(user["user_id"], "UPLOAD", f"{original}; file_id={file_id}; replicas={FACTOR}")
            chunk_count = fetch_one("SELECT COUNT(*) n FROM file_chunks WHERE file_id=%s", (file_id,))["n"]
            flash(f"Upload successful: split into {chunk_count} chunk(s), with up to {FACTOR} replicas per chunk.", "success")
        except Exception as exc:
            execute("UPDATE files SET deleted=1 WHERE file_id=%s", (file_id,))
            execute("UPDATE file_requests SET file_id=%s,status='FAILED',completed_at=NOW(),details=%s WHERE request_id=%s",
                    (file_id, str(exc)[:900], request_id))
            raise
    except Exception as exc:
        flash(f"Upload failed: {exc}", "danger")
    finally:
        if temp.exists():
            temp.unlink()
    return redirect(url_for("dashboard"))

@app.route("/download/<int:file_id>")
@login_required
def download(file_id):
    user = user_now()
    row = fetch_one("SELECT * FROM files WHERE file_id=%s AND deleted=0", (file_id,))
    if not row or not can_access(row, user):
        abort(404)
    req_id = create_request(user["user_id"], "DOWNLOAD", 5, file_id, row["original_name"])
    execute("UPDATE file_requests SET status='PROCESSING' WHERE request_id=%s", (req_id,))
    output = TEMP_ROOT / f"download_{file_id}_{uuid.uuid4().hex}.bin"
    try:
        reconstruct_file(row, output)
        execute("UPDATE file_requests SET status='COMPLETED',completed_at=NOW() WHERE request_id=%s", (req_id,))
        log_action(user["user_id"], "DOWNLOAD", f"{row['original_name']} reconstructed from distributed chunks")
        response = send_file(output, as_attachment=True, download_name=row["original_name"], conditional=True)
        response.call_on_close(lambda: output.unlink(missing_ok=True))
        return response
    except Exception as exc:
        output.unlink(missing_ok=True)
        execute("UPDATE file_requests SET status='FAILED',completed_at=NOW(),details=%s WHERE request_id=%s", (str(exc)[:900], req_id))
        log_action(user["user_id"], "DOWNLOAD_FAILED", f"file={file_id}; {exc}")
        flash(f"File recovery failed: {exc}", "danger")
        return redirect(url_for("dashboard"))

@app.route("/stream/<int:file_id>")
@login_required
def stream_file(file_id):
    user = user_now()
    row = fetch_one("SELECT * FROM files WHERE file_id=%s AND deleted=0", (file_id,))
    if not row or not can_access(row, user):
        abort(404)
    # Reassemble once per play request; send_file's conditional response supports HTTP byte ranges.
    output = TEMP_ROOT / f"stream_{file_id}_{uuid.uuid4().hex}.bin"
    try:
        reconstruct_file(row, output)
    except Exception as exc:
        output.unlink(missing_ok=True)
        flash(f"Playback could not start: {exc}", "danger")
        return redirect(url_for("dashboard"))
    mimetype = row.get("content_type") or "application/octet-stream"
    response = send_file(output, mimetype=mimetype, conditional=True, etag=True, max_age=0)
    response.call_on_close(lambda: output.unlink(missing_ok=True))
    log_action(user["user_id"], "STREAM", f"{row['original_name']} reconstructed from chunks")
    return response

@app.route("/player/<int:file_id>")
@login_required
def player(file_id):
    user = user_now()
    row = fetch_one("SELECT * FROM files WHERE file_id=%s AND deleted=0", (file_id,))
    if not row or not can_access(row, user):
        abort(404)
    if not (row.get("content_type") or "").startswith("video/"):
        flash("This file is not detected as a video. You can download it instead.", "danger")
        return redirect(url_for("dashboard"))
    return render_template("player.html", file=row)

@app.route("/delete/<int:file_id>", methods=["POST"])
@login_required
def delete_file(file_id):
    user = user_now()
    row = fetch_one("SELECT * FROM files WHERE file_id=%s AND deleted=0", (file_id,))
    if not row or not can_access(row, user, write=True):
        abort(403)
    execute("UPDATE files SET deleted=1 WHERE file_id=%s", (file_id,))
    log_action(user["user_id"], "DELETE", row["original_name"])
    flash("File moved to recycle bin. Replica bytes are retained for audit/recovery.", "success")
    return redirect(url_for("dashboard"))

@app.route("/share/<int:file_id>", methods=["GET", "POST"])
@login_required
def share(file_id):
    user = user_now()
    row = fetch_one("SELECT * FROM files WHERE file_id=%s AND deleted=0", (file_id,))
    if not row or (int(row["owner_id"]) != int(user["user_id"]) and user["role"] != "admin"):
        abort(403)
    users = fetch_all("SELECT user_id,username FROM users WHERE user_id<>%s ORDER BY username", (user["user_id"],))
    if request.method == "POST":
        target = request.form.get("user_id", type=int)
        access = request.form.get("access", "read")
        if not fetch_one("SELECT user_id FROM users WHERE user_id=%s", (target,)):
            flash("User not found.", "danger")
        else:
            execute("""INSERT INTO file_permissions(file_id,user_id,can_read,can_write) VALUES(%s,%s,1,%s)
                ON DUPLICATE KEY UPDATE can_read=1,can_write=VALUES(can_write)""",
                (file_id, target, 1 if access == "write" else 0))
            log_action(user["user_id"], "SHARE", f"file={file_id}; user={target}; access={access}")
            flash("Permissions saved.", "success")
            return redirect(url_for("dashboard"))
    return render_template("share.html", file=row, users=users)

@app.route("/health/<int:file_id>")
@login_required
def health(file_id):
    user = user_now()
    row = fetch_one("SELECT * FROM files WHERE file_id=%s AND deleted=0", (file_id,))
    if not row or not can_access(row, user):
        abort(404)
    chunks = fetch_all("SELECT chunk_index,size_bytes,sha256 FROM file_chunks WHERE file_id=%s ORDER BY chunk_index", (file_id,))
    replicas = chunk_health(file_id)
    return render_template("health.html", file=row, replicas=replicas, chunks=chunks)

@app.route("/admin")
@login_required
def admin():
    user = user_now()
    if user["role"] != "admin":
        abort(403)
    users = fetch_all("SELECT user_id,username,role,created_at FROM users ORDER BY user_id")
    nodes = fetch_all("SELECT * FROM storage_nodes ORDER BY node_id")
    replicas = fetch_all("""SELECT cr.chunk_replica_id replica_id, cr.replica_status, cr.relative_path, n.node_name, f.original_name, ch.chunk_index, ch.file_id
        FROM chunk_replicas cr JOIN storage_nodes n ON n.node_id=cr.node_id
        JOIN file_chunks ch ON ch.chunk_id=cr.chunk_id JOIN files f ON f.file_id=ch.file_id
        ORDER BY ch.file_id,ch.chunk_index,n.node_id""")
    logs = fetch_all("""SELECT a.*,u.username FROM audit_logs a LEFT JOIN users u ON u.user_id=a.user_id
        ORDER BY a.log_id DESC LIMIT 100""")
    requests = fetch_all("""SELECT r.*,u.username,f.original_name FROM file_requests r
        JOIN users u ON u.user_id=r.user_id LEFT JOIN files f ON f.file_id=r.file_id
        ORDER BY CASE WHEN r.status='QUEUED' THEN 0 ELSE 1 END, r.priority ASC, r.created_at ASC LIMIT 100""")
    scheduled = priority_schedule([r for r in requests if r["status"] == "QUEUED"])
    return render_template("admin.html", users=users, nodes=nodes, replicas=replicas, logs=logs,
                           requests=requests, scheduled=scheduled)

@app.route("/admin/node/<int:node_id>/toggle", methods=["POST"])
@login_required
def toggle_node(node_id):
    user = user_now()
    if user["role"] != "admin":
        abort(403)
        
    node = fetch_one("SELECT * FROM storage_nodes WHERE node_id=%s", (node_id,))
    if not node:
        abort(404)
    status = "OFFLINE" if node["status"] == "ONLINE" else "ONLINE"
    if status == "OFFLINE":
        total = 0
        for row in fetch_all("SELECT * FROM files WHERE deleted=0"):
            try:
                total += repair_chunk_replicas(int(row["file_id"]), FACTOR, exclude_node_id=node_id)
            except Exception as exc:
                log_action(user["user_id"], "REPAIR_ERROR", f"file={row['file_id']}: {exc}")
        execute("UPDATE storage_nodes SET status='OFFLINE' WHERE node_id=%s", (node_id,))
        log_action(user["user_id"], "NODE_STATUS", f"{node['node_name']} -> OFFLINE")
        log_action(user["user_id"], "REPAIR", f"Created {total} replica(s) before {node['node_name']} offline")
        flash(f"{node['node_name']} set to OFFLINE. Repair created {total} replica(s).", "success")
    else:
        execute("UPDATE storage_nodes SET status='ONLINE' WHERE node_id=%s", (node_id,))
        log_action(user["user_id"], "NODE_STATUS", f"{node['node_name']} -> ONLINE")
        flash(f"{node['node_name']} set to ONLINE.", "success")
    return redirect(url_for("admin"))

@app.route("/admin/node/<int:node_id>/refresh", methods=["POST"])
@login_required
def refresh_node(node_id):
    user = user_now()
    if user["role"] != "admin":
        abort(403)
    try:
        from storage import probe_node
        node = fetch_one("SELECT * FROM storage_nodes WHERE node_id=%s", (node_id,))
        if not node:
            abort(404)
        info = probe_node(node)
        execute("UPDATE storage_nodes SET used_bytes=%s, last_heartbeat=NOW() WHERE node_id=%s",
                (info["used_bytes"], node_id))
        log_action(user["user_id"], "NODE_REFRESH", f"{node['node_name']} checked ({info['mode']})")
        flash(f"{node['node_name']} refreshed: {info['used_bytes']} bytes used.", "success")
    except Exception as exc:
        log_action(user["user_id"], "NODE_REFRESH_ERROR", f"{node_id}: {exc}")
        flash(f"Node check failed: {exc}", "danger")
    return redirect(url_for("admin"))

@app.route("/admin/node/add", methods=["POST"])
@login_required
def add_node():
    user = user_now()
    if user["role"] != "admin":
        abort(403)
    name = request.form.get("node_name", "").strip()
    base_path = request.form.get("base_path", "").strip()
    node_url = request.form.get("node_url", "").strip() or None
    capacity_mb = int(request.form.get("capacity_mb", "10240"))
    if not name or not base_path:
        flash("Node name and storage path are required.", "danger")
        return redirect(url_for("admin"))
    try:
        execute("INSERT INTO storage_nodes(node_name,base_path,node_url,capacity_bytes,status) VALUES(%s,%s,%s,%s,'ONLINE')",
                (name, base_path, node_url, capacity_mb * 1024 * 1024))
        log_action(user["user_id"], "NODE_ADD", f"{name} ({node_url or 'local'})")
        flash(f"Node {name} added.", "success")
    except Exception as exc:
        flash(f"Failed to add node: {exc}", "danger")
    return redirect(url_for("admin"))

@app.route("/admin/repair", methods=["POST"])
@login_required
def repair():
    user = user_now()
    if user["role"] != "admin":
        abort(403)
    rows = fetch_all("SELECT * FROM files WHERE deleted=0")
    total = 0
    for row in rows:
        try:
            total += repair_chunk_replicas(int(row["file_id"]), FACTOR)
        except Exception as exc:
            log_action(user["user_id"], "REPAIR_ERROR", f"file={row['file_id']}: {exc}")
    log_action(user["user_id"], "REPAIR", f"Created {total} replica(s)")
    flash(f"Repair complete. Created {total} replica(s).", "success")
    return redirect(url_for("admin"))

@app.route("/admin/scheduler")
@login_required
def scheduler_demo():
    user = user_now()
    if user["role"] != "admin":
        abort(403)
    queued = fetch_all("SELECT * FROM file_requests WHERE status='QUEUED' ORDER BY created_at")
    return render_template("scheduler.html", priority=priority_schedule(queued), fcfs=fcfs_schedule(queued))

@app.errorhandler(403)
def forbidden(_):
    return render_template("error.html", code=403, message="You do not have permission to access this resource."), 403

@app.errorhandler(404)
def not_found(_):
    return render_template("error.html", code=404, message="The requested resource was not found."), 404

@app.errorhandler(413)
def too_large(_):
    flash(f"Upload exceeds the configured {MAX_BYTES // (1024*1024)} MB limit.", "danger")
    return redirect(url_for("dashboard"))

if __name__ == "__main__":
    app.run(debug=True)