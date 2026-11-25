from __future__ import annotations

import hashlib
import json
import os
import threading
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from db import execute, fetch_all, fetch_one

UPLOAD_LOCK = threading.Lock()
TEMP_ROOT = Path(os.getenv("TEMP_DIR", "./uploads_tmp"))
TEMP_ROOT.mkdir(parents=True, exist_ok=True)
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE_MB", "4")) * 1024 * 1024
NODE_TIMEOUT = float(os.getenv("NODE_REQUEST_TIMEOUT_SECONDS", "10"))
NODE_SHARED_TOKEN = os.getenv("NODE_SHARED_TOKEN", "")


def _remote(node: dict) -> bool:
    return bool((node.get("node_url") or "").strip())


def _key(stored_name: str, index: int) -> str:
    return f"chunks/{stored_name}.c{index:04d}"


def _request(node: dict, method: str, endpoint: str, data: bytes | None = None) -> bytes:
    headers = {"X-Node-Token": NODE_SHARED_TOKEN}
    if data is not None:
        headers["Content-Type"] = "application/octet-stream"
    request = Request(f"{node['node_url'].rstrip('/')}{endpoint}", data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=NODE_TIMEOUT) as response:
            return response.read()
    except HTTPError as exc:
        raise RuntimeError(f"Node {node['node_name']} returned HTTP {exc.code}: {exc.read().decode(errors='replace')[:200]}") from exc
    except URLError as exc:
        raise RuntimeError(f"Cannot contact node {node['node_name']}: {exc.reason}") from exc


def _path(node: dict, key: str) -> Path:
    root = Path(node["base_path"]).resolve()
    candidate = Path(key)
    path = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    if path != root and root not in path.parents:
        raise RuntimeError("Invalid chunk path")
    return path


def _put(node: dict, key: str, data: bytes) -> None:
    if _remote(node):
        _request(node, "PUT", f"/chunks/{quote(key, safe='/')}", data)
    else:
        path = _path(node, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def _get(node: dict, key: str) -> bytes:
    if _remote(node):
        return _request(node, "GET", f"/chunks/{quote(key, safe='/')}")
    path = _path(node, key)
    if not path.exists():
        raise RuntimeError(f"Chunk missing: {key}")
    return path.read_bytes()


def _delete(node: dict, key: str) -> None:
    try:
        if _remote(node):
            _request(node, "DELETE", f"/chunks/{quote(key, safe='/')}")
        else:
            _path(node, key).unlink(missing_ok=True)
    except Exception:
        pass


def _check(node: dict, key: str, digest: str) -> tuple[bool, bool]:
    try:
        if _remote(node):
            payload = json.loads(_request(node, "GET", f"/chunks/{quote(key, safe='/')}/health").decode())
            exists = bool(payload.get("exists"))
            return exists, exists and payload.get("sha256") == digest
        path = _path(node, key)
        return (False, False) if not path.exists() else (True, hashlib.sha256(path.read_bytes()).hexdigest() == digest)
    except Exception:
        return False, False


def _used(node: dict) -> int:
    if _remote(node):
        return int(json.loads(_request(node, "GET", "/stats").decode()).get("used_bytes", 0))
    root = Path(node["base_path"]).resolve()
    return sum(item.stat().st_size for item in root.rglob("*") if item.is_file()) if root.exists() else 0


def _refresh(nodes: list[dict]) -> None:
    for node in nodes:
        try:
            execute("UPDATE storage_nodes SET used_bytes=%s WHERE node_id=%s", (_used(node), node["node_id"]))
        except Exception:
            pass


def init_storage() -> None:
    for node in fetch_all("SELECT * FROM storage_nodes WHERE status='ONLINE'"):
        if not _remote(node):
            Path(node["base_path"]).resolve().mkdir(parents=True, exist_ok=True)


def probe_node(node: dict) -> dict:
    if not _remote(node):
        Path(node["base_path"]).resolve().mkdir(parents=True, exist_ok=True)
        return {"ok": True, "used_bytes": _used(node), "mode": "local"}
    health = json.loads(_request(node, "GET", "/health").decode())
    if not health.get("ok"):
        raise RuntimeError(f"Node {node['node_name']} reported unhealthy")
    return {"ok": True, "used_bytes": _used(node), "mode": "remote"}


def store_chunked_file(file_id: int, temp_path: str, replication_factor: int = 2) -> None:
    with UPLOAD_LOCK:
        file_row = fetch_one("SELECT * FROM files WHERE file_id=%s AND deleted=0", (file_id,))
        if not file_row:
            raise RuntimeError(f"File record {file_id} not found or deleted")
        payload = Path(temp_path).read_bytes()
        if len(payload) != int(file_row["size_bytes"]) or hashlib.sha256(payload).hexdigest() != file_row["sha256"]:
            raise RuntimeError("Uploaded file failed size or SHA-256 validation")
        nodes = fetch_all("SELECT * FROM storage_nodes WHERE status='ONLINE' ORDER BY (capacity_bytes-used_bytes) DESC,node_id")
        if not nodes:
            raise RuntimeError("No online storage nodes available in the cluster")
        rf = max(1, min(int(replication_factor), len(nodes)))
        pieces = [payload[pos:pos + CHUNK_SIZE] for pos in range(0, len(payload), CHUNK_SIZE)] or [b""]
        written: list[tuple[dict, str]] = []
        try:
            for index, piece in enumerate(pieces):
                key, digest = _key(file_row["stored_name"], index), hashlib.sha256(piece).hexdigest()
                selected = [nodes[(index + offset) % len(nodes)] for offset in range(rf)]
                for node in selected:
                    _put(node, key, piece)
                    written.append((node, key))
                chunk_id, _ = execute("INSERT INTO file_chunks(file_id,chunk_index,size_bytes,sha256) VALUES(%s,%s,%s,%s)", (file_id, index, len(piece), digest))
                for node in selected:
                    execute("INSERT INTO chunk_replicas(chunk_id,node_id,relative_path,replica_status) VALUES(%s,%s,%s,'HEALTHY')", (chunk_id, node["node_id"], key))
            _refresh(nodes)
        except Exception:
            for node, key in written:
                _delete(node, key)
            raise


def reconstruct_file(file_row: dict, output_path: str | Path) -> None:
    chunks = fetch_all("SELECT chunk_id,chunk_index,size_bytes,sha256 FROM file_chunks WHERE file_id=%s ORDER BY chunk_index", (file_row["file_id"],))
    if not chunks:
        raise RuntimeError(f"No chunks found for file {file_row['file_id']}")
    output = Path(output_path)
    with open(output, "wb") as out:
        for chunk in chunks:
            replicas = fetch_all("""SELECT cr.chunk_replica_id,cr.relative_path,n.node_name,n.base_path,n.node_url,n.status
                                  FROM chunk_replicas cr JOIN storage_nodes n ON n.node_id=cr.node_id
                                  WHERE cr.chunk_id=%s AND cr.replica_status='HEALTHY' AND n.status='ONLINE'""", (chunk["chunk_id"],))
            for replica in replicas:
                try:
                    data = _get(replica, replica["relative_path"])
                    if len(data) == int(chunk["size_bytes"]) and hashlib.sha256(data).hexdigest() == chunk["sha256"]:
                        out.write(data)
                        break
                    execute("UPDATE chunk_replicas SET replica_status='CORRUPT' WHERE chunk_replica_id=%s", (replica["chunk_replica_id"],))
                except Exception:
                    execute("UPDATE chunk_replicas SET replica_status='MISSING' WHERE chunk_replica_id=%s", (replica["chunk_replica_id"],))
            else:
                raise RuntimeError(f"No valid replica for chunk {chunk['chunk_index']}")
    if output.stat().st_size != int(file_row["size_bytes"]) or sha256_file(output) != file_row["sha256"]:
        output.unlink(missing_ok=True)
        raise RuntimeError("Reconstructed file failed final checksum validation")


def repair_chunk_replicas(file_id: int, factor: int = 2, exclude_node_id: int | None = None) -> int:
    nodes = fetch_all("SELECT * FROM storage_nodes WHERE status='ONLINE' ORDER BY (capacity_bytes-used_bytes) DESC,node_id")
    if exclude_node_id is not None:
        nodes = [n for n in nodes if int(n["node_id"]) != int(exclude_node_id)]
    target = max(1, min(int(factor), len(nodes))) if nodes else 0
    created = 0
    for chunk in fetch_all("SELECT chunk_id,sha256 FROM file_chunks WHERE file_id=%s", (file_id,)):
        replicas = fetch_all("""SELECT cr.chunk_replica_id,cr.node_id,cr.relative_path,cr.replica_status,n.node_name,n.base_path,n.node_url,n.status node_status
                              FROM chunk_replicas cr JOIN storage_nodes n ON n.node_id=cr.node_id WHERE cr.chunk_id=%s""", (chunk["chunk_id"],))
        valid, source_data, key = set(), None, None
        for replica in replicas:
            if exclude_node_id is not None and int(replica["node_id"]) == int(exclude_node_id):
                if replica["replica_status"] != "MISSING":
                    execute("UPDATE chunk_replicas SET replica_status='MISSING' WHERE chunk_replica_id=%s", (replica["chunk_replica_id"],))
                continue
            if replica.get("node_status") != "ONLINE":
                if replica["replica_status"] != "MISSING":
                    execute("UPDATE chunk_replicas SET replica_status='MISSING' WHERE chunk_replica_id=%s", (replica["chunk_replica_id"],))
                continue
            exists, ok = _check(replica, replica["relative_path"], chunk["sha256"])
            status = "HEALTHY" if ok else ("MISSING" if not exists else "CORRUPT")
            if status != replica["replica_status"]:
                execute("UPDATE chunk_replicas SET replica_status=%s WHERE chunk_replica_id=%s", (status, replica["chunk_replica_id"]))
            if ok:
                valid.add(int(replica["node_id"]))
                if source_data is None:
                    source_data, key = _get(replica, replica["relative_path"]), replica["relative_path"]
        if source_data is None:
            continue
        for node in [node for node in nodes if int(node["node_id"]) not in valid][:max(0, target - len(valid))]:
            _put(node, key, source_data)
            execute("INSERT INTO chunk_replicas(chunk_id,node_id,relative_path,replica_status) VALUES(%s,%s,%s,'HEALTHY')", (chunk["chunk_id"], node["node_id"], key))
            created += 1
    _refresh(nodes)
    return created


def chunk_health(file_id: int) -> list[dict]:
    rows = fetch_all("""SELECT fc.chunk_index,fc.sha256,cr.chunk_replica_id,cr.replica_status,cr.relative_path,sn.node_name,sn.base_path,sn.node_url,sn.status node_status
                        FROM file_chunks fc JOIN chunk_replicas cr ON cr.chunk_id=fc.chunk_id JOIN storage_nodes sn ON sn.node_id=cr.node_id
                        WHERE fc.file_id=%s ORDER BY fc.chunk_index,sn.node_name""", (file_id,))
    result = []
    for row in rows:
        if row["node_status"] != "ONLINE":
            exists, valid = False, False
            status = "MISSING"
        else:
            exists, valid = _check(row, row["relative_path"], row["sha256"])
            status = "HEALTHY" if valid else ("MISSING" if not exists else "CORRUPT")
        if status != row["replica_status"]:
            execute("UPDATE chunk_replicas SET replica_status=%s WHERE chunk_replica_id=%s", (status, row["chunk_replica_id"]))
        result.append({"chunk_index": row["chunk_index"], "node": row["node_name"], "exists": exists, "valid": valid, "status": status, "node_status": row["node_status"]})
    return result


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for block in iter(lambda: file.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()
