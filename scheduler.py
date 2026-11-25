"""Operating-system scheduling demonstrations used by DFMS."""
from dataclasses import dataclass
from typing import List

@dataclass
class Request:
    request_id: int
    priority: int
    created_at: str
    operation: str = "UPLOAD"

def priority_schedule(requests: List[dict]) -> List[dict]:
    """Smaller number means higher priority; ties use arrival/creation order."""
    return sorted(requests, key=lambda r: (int(r.get("priority", 5)), str(r.get("created_at", "")), int(r.get("request_id", 0))))

def fcfs_schedule(requests: List[dict]) -> List[dict]:
    """First-Come-First-Served: oldest request first."""
    return sorted(requests, key=lambda r: (str(r.get("created_at", "")), int(r.get("request_id", 0))))

def sstf_schedule(head: int, requests: List[dict]) -> List[dict]:
    """Shortest Seek Time First disk scheduling. Each request needs a numeric block/track."""
    pending = [dict(r) for r in requests]
    order, current = [], int(head)
    while pending:
        chosen = min(pending, key=lambda r: (abs(int(r.get("track", 0)) - current), int(r.get("request_id", 0))))
        pending.remove(chosen)
        chosen["seek_distance"] = abs(int(chosen.get("track", 0)) - current)
        order.append(chosen)
        current = int(chosen.get("track", 0))
    return order