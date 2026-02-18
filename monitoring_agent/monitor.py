import os
import time
import socket
import math
from collections import Counter
from datetime import datetime

import boto3
from botocore.client import Config, BaseClient
import redis
import psutil
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from dotenv import load_dotenv

load_dotenv()


# ======================
# Configuration
# ======================
WATCH_PATH = os.environ.get("WATCH_PATH", "/utils/test_files")
REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))
STREAM_NAME_FILE_INFO = "file_info"
STREAM_NAME_PING = "ping"
SNAPSHOT_DIR = os.environ.get("SNAPSHOT_DIR", "/utils/snapshots")
NODE_ID = socket.gethostname()
S3_ENDPOINT = os.environ.get("S3_ENDPOINT", "http://localhost:9333")
S3_BUCKET = os.environ.get("S3_BUCKET", "files")
S3_ACCESS_KEY = os.environ.get("S3_ACCESS_KEY")
S3_SECRET_KEY = os.environ.get("S3_SECRET_KEY")
CHUNK_SIZE = 65536  # 64 KB


# ======================
# Utility functions
# ======================
def calculate_entropy(file_path):
    counts = Counter()
    total_size = 0

    try:
        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(CHUNK_SIZE)
                if not chunk:
                    break
                counts.update(chunk)
                total_size += len(chunk)
    except Exception as e:
        print(f"[MONITOR] Failed to calculate entropy, falling back to 0.0: {e}")
        return 0.0

    if total_size == 0:
        return 0.0

    entropy = 0.0
    for count in counts.values():
        p = count / total_size
        entropy -= p * math.log2(p)

    return round(entropy, 4)


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
    def __init__(self, redis_client, s3_client: BaseClient):
        self.redis = redis_client
        self.s3_client = s3_client
        
    def ping_online(self):
        event = {
            "timestamp": datetime.utcnow().isoformat(),
            "node_id": NODE_ID,
            "event_type": "ONLINE",
        }

        self.redis.xadd(STREAM_NAME_PING, event)

    def send_event(self, file_path, event_type):
        event = {
            "timestamp": datetime.utcnow().isoformat(),
            "node_id": NODE_ID,
            "file_path": file_path,
            "event_type": event_type,
            "entropy": calculate_entropy(file_path),
            "process_name": get_process_name(file_path),
            "backup_version_id": self.latest_snapshot_id(),
        }

        self.redis.xadd(STREAM_NAME_FILE_INFO, event)
        print(f"[MONITOR] {event_type} -> {file_path}")

    def on_modified(self, event):
        if not event.is_directory:
            self.send_event(event.src_path, "FILE_MODIFIED")

    def on_created(self, event):
        if not event.is_directory:
            self.send_event(event.src_path, "FILE_CREATED")
            
    def latest_snapshot_id(self):
        try:
            response = self.s3_client.list_objects_v2(Bucket=S3_BUCKET, Prefix=f"/{NODE_ID}")
            if "Contents" in response:
                latest = max(response["Contents"], key=lambda x: x["LastModified"])
                return latest["Key"]
        except Exception:
            pass
        return "none"


# ======================
# Main
# ======================
def main():
    print(f"[MONITOR] Starting on node {NODE_ID}")
    print(f"[MONITOR] Watching path: {WATCH_PATH}")

    redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    s3_client = boto3.client(
        "s3",
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY,
        endpoint_url=S3_ENDPOINT,
        config=Config(signature_version="s3v4"),
        region_name="us-east-1",
    )

    handler = FileMonitorHandler(redis_client, s3_client)
    observer = Observer()
    observer.schedule(handler, WATCH_PATH, recursive=True)
    observer.start()

    try:
        while True:
            time.sleep(1)
            handler.ping_online()
    except KeyboardInterrupt:
        observer.stop()

    observer.join()


if __name__ == "__main__":
    main()