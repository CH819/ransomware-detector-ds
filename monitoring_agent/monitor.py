import os
import time
import socket
import hashlib
from collections import Counter
from datetime import datetime

import redis
import psutil
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler


# ======================
# Configuration
# ======================
WATCH_PATH = os.environ.get("WATCH_PATH", "/data")
REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))
STREAM_NAME = "file_events"
SNAPSHOT_DIR = os.environ.get("SNAPSHOT_DIR", "/snapshots")
NODE_ID = socket.gethostname()


# ======================
# Utility functions
# ======================
def calculate_entropy(file_path):
    try:
        with open(file_path, "rb") as f:
            data = f.read()
        if not data:
            return 0.0

        counts = Counter(data)
        length = len(data)
        entropy = 0.0
        for count in counts.values():
            p = count / length
            entropy -= p * (p.bit_length() / 8)

        return round(entropy, 4)
    except Exception:
        return 0.0


def get_process_name(file_path):
    try:
        for proc in psutil.process_iter(["pid", "name", "open_files"]):
            try:
                for f in proc.info.get("open_files") or []:
                    if f.path == file_path:
                        return proc.info["name"]
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception:
        pass
    return "unknown"


def latest_snapshot_id():
    try:
        if not os.path.exists(SNAPSHOT_DIR):
            return "none"
        snapshots = sorted(os.listdir(SNAPSHOT_DIR))
        return snapshots[-1] if snapshots else "none"
    except Exception:
        return "none"


# ======================
# Monitor Handler
# ======================
class FileMonitorHandler(FileSystemEventHandler):
    def __init__(self, redis_client):
        self.redis = redis_client

    def send_event(self, file_path, event_type):
        event = {
            "timestamp": datetime.utcnow().isoformat(),
            "node_id": NODE_ID,
            "file_path": file_path,
            "event_type": event_type,
            "entropy": str(calculate_entropy(file_path)),
            "process_name": get_process_name(file_path),
            "backup_version_id": latest_snapshot_id(),
        }

        self.redis.xadd(STREAM_NAME, event)
        print(f"[MONITOR] {event_type} -> {file_path}")

    def on_modified(self, event):
        if not event.is_directory:
            self.send_event(event.src_path, "FILE_MODIFIED")

    def on_created(self, event):
        if not event.is_directory:
            self.send_event(event.src_path, "FILE_CREATED")


# ======================
# Main
# ======================
def main():
    print(f"[MONITOR] Starting on node {NODE_ID}")
    print(f"[MONITOR] Watching path: {WATCH_PATH}")

    redis_client = redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        decode_responses=True
    )

    handler = FileMonitorHandler(redis_client)
    observer = Observer()
    observer.schedule(handler, WATCH_PATH, recursive=True)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()

    observer.join()


if __name__ == "__main__":
    main()
