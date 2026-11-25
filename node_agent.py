"""Authenticated storage service. Run this file on every physical storage PC."""
import argparse
import hashlib
import os
import shutil
import tempfile
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, Response, abort, jsonify, request

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
app = Flask(__name__)

# Parse command-line args to allow running multiple nodes on one machine
parser = argparse.ArgumentParser(description="DFMS Storage Node Agent")
parser.add_argument("--name", default=os.getenv("NODE_NAME", "storage-node"))
parser.add_argument("--storage-dir", default=os.getenv("NODE_STORAGE_DIR", "./node_storage"))
parser.add_argument("--host", default=os.getenv("NODE_AGENT_HOST", "0.0.0.0"))
parser.add_argument("--port", type=int, default=int(os.getenv("NODE_AGENT_PORT", "7001")))
parser.add_argument("--token", default=os.getenv("NODE_SHARED_TOKEN", ""))
args = parser.parse_args()

STORAGE_ROOT = Path(args.storage_dir).resolve()
TOKEN = args.token
NAME = args.name
HOST = args.host
PORT = args.port
STORAGE_ROOT.mkdir(parents=True, exist_ok=True)


def _path(key: str) -> Path:
    if not key or "\\" in key:
        abort(400, "Invalid chunk key")
    path = (STORAGE_ROOT / key).resolve()
    if path != STORAGE_ROOT and STORAGE_ROOT not in path.parents:
        abort(400, "Invalid chunk key")
    return path


@app.before_request
def authorize():
    if not TOKEN or request.headers.get("X-Node-Token") != TOKEN:
        abort(401, "Invalid node token")


@app.get("/health")
def health():
    return jsonify(ok=True, node_name=NAME)


@app.get("/stats")
def stats():
    used = sum(item.stat().st_size for item in STORAGE_ROOT.rglob("*") if item.is_file())
    disk = shutil.disk_usage(STORAGE_ROOT)
    return jsonify(ok=True, node_name=NAME, used_bytes=used, capacity_bytes=disk.total, free_bytes=disk.free)


@app.put("/chunks/<path:key>")
def put_chunk(key):
    data = request.get_data(cache=False)
    target = _path(key)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as temp:
        temp.write(data)
        temp_name = temp.name
    os.replace(temp_name, target)
    return jsonify(ok=True, key=key, size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest())


@app.get("/chunks/<path:key>")
def get_chunk(key):
    path = _path(key)
    if not path.is_file():
        abort(404, "Chunk not found")
    return Response(path.read_bytes(), mimetype="application/octet-stream")


@app.delete("/chunks/<path:key>")
def delete_chunk(key):
    _path(key).unlink(missing_ok=True)
    return jsonify(ok=True, key=key)


@app.get("/chunks/<path:key>/health")
def chunk_health(key):
    path = _path(key)
    if not path.is_file():
        return jsonify(ok=True, exists=False, key=key)
    data = path.read_bytes()
    return jsonify(ok=True, exists=True, key=key, size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest())


if __name__ == "__main__":
    app.run(host=HOST, port=PORT, debug=False)