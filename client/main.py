from watchdog.events import FileModifiedEvent
from watchdog.events import DirModifiedEvent
import uuid
import os
import time
import math
import logging
import threading
import shutil
from collections import Counter
from datetime import datetime as dt

import boto3
from botocore.client import Config
import redis
import psutil
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from flask import Flask, jsonify, request
from dotenv import load_dotenv

load_dotenv()

# ======================
# Configuration
# ======================
WATCH_PATH = os.environ.get("WATCH_PATH", "/nodes")
NODE_ID = os.environ.get("NODE_ID", f"{uuid.uuid4()}")
WATCH_NODE_PATH = os.path.join(WATCH_PATH, NODE_ID)

REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))
STREAM_NAME_FILE_INFO = "file_info"
STREAM_NAME_PING = "ping"

S3_ENDPOINT = os.environ.get("S3_ENDPOINT", "http://s3:9333")
S3_BUCKET = os.environ.get("S3_BUCKET", "files")
S3_ACCESS_KEY = os.environ.get("S3_ACCESS_KEY")
S3_SECRET_KEY = os.environ.get("S3_SECRET_KEY")

TEMP_DIR = os.environ.get("TEMP_DIR", "/tmp")
APP_PORT = int(os.environ.get("CLIENT_PORT", 7000))
BACKUP_INTERVAL_SECONDS = int(os.environ.get("BACKUP_INTERVAL", 10))

CHUNK_SIZE = 65536  # 64 KB

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - CLIENT - %(levelname)s - %(message)s\n",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Clients
redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
s3_client = boto3.client(
    "s3",
    aws_access_key_id=S3_ACCESS_KEY,
    aws_secret_access_key=S3_SECRET_KEY,
    endpoint_url=S3_ENDPOINT,
    config=Config(signature_version="s3v4"),
    region_name="us-east-1",
)

# Shared state variable that blocks file monitoring during recovery
RECOVERY_MODE = threading.Event()


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
        logger.error(f"[MONITOR] Failed to calculate entropy, falling back to 0.0: {e}")
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


# ======================
# Monitor Handler
# ======================
class FileMonitorHandler(FileSystemEventHandler):
    def __init__(self, r_client, s_client):
        self.redis = r_client
        self.s3_client = s_client
        self.last_stats: dict[str, tuple[float, int]] = {}  # path -> (mtime, size)

        if os.path.exists(WATCH_NODE_PATH):
            for root, _, files in os.walk(WATCH_NODE_PATH):
                for name in files:
                    file_path = os.path.join(root, name)
                    stats = self.get_file_stats(file_path)
                    if stats:
                        self.last_stats[file_path] = stats

    def ping_online(self):
        event = {
            "timestamp": int(time.time() * 1000),
            "node_id": NODE_ID,
            "event_type": "ONLINE",
        }
        try:
            self.redis.xadd(STREAM_NAME_PING, event)
        except Exception as e:
            logger.error(f"Failed to ping gateway: {e}")

    def get_file_stats(self, file_path):
        try:
            stat = os.stat(file_path)
            return (stat.st_mtime, stat.st_size)
        except Exception:
            return None

    def is_real_file_change(self, event: FileModifiedEvent):
        current_stats = self.get_file_stats(event.src_path)
        prev_stats = self.last_stats.get(event.src_path)
        if current_stats and prev_stats == current_stats:
            # Stats haven't changed, likely a metadata-only change
            return False

        if current_stats:
            self.last_stats[event.src_path] = current_stats

        return True

    def send_event(self, file_path, event_type):
        event = {
            "timestamp": int(time.time() * 1000),
            "node_id": NODE_ID,
            "file_path": file_path,
            "event_type": event_type,
            "entropy": calculate_entropy(file_path),
            "process_name": get_process_name(file_path),
            "backup_version_id": self.latest_snapshot_id(),
        }

        try:
            self.redis.xadd(STREAM_NAME_FILE_INFO, event)
            logger.info(f"[MONITOR] {event_type} -> {file_path}")
        except Exception as e:
            logger.error(f"Failed to send event to stream: {e}")

    def on_modified(self, event: DirModifiedEvent | FileModifiedEvent):
        if RECOVERY_MODE.is_set():
            return
        if not event.is_directory and self.is_real_file_change(event):
            self.send_event(event.src_path, "FILE_MODIFIED")

    def on_created(self, event: DirModifiedEvent | FileModifiedEvent):
        if RECOVERY_MODE.is_set():
            return
        if not event.is_directory and self.is_real_file_change(event):
            self.send_event(event.src_path, "FILE_CREATED")

    def latest_snapshot_id(self):
        try:
            response = self.s3_client.list_objects_v2(
                Bucket=S3_BUCKET, Prefix=f"{NODE_ID}/snapshot_"
            )
            if "Contents" in response:
                latest = max(response["Contents"], key=lambda x: x["LastModified"])
                # Extract filename without .zip
                key = latest["Key"]
                return os.path.basename(key).replace(".zip", "")
        except Exception as e:
            logger.debug(f"Could not get latest snapshot ID: {e}")
        return "none"


# ======================
# Snapshot Logic
# ======================
def capture_snapshot(node_id):
    timestamp = int(time.time() * 1000)
    zip_filename = f"snapshot_{node_id}_{timestamp}"
    zip_filepath = os.path.join(TEMP_DIR, zip_filename)
    zip_source = os.path.join(WATCH_PATH, node_id)

    try:
        os.makedirs(TEMP_DIR, exist_ok=True)
        if not os.path.exists(zip_source):
            logger.warning(f"Source path {zip_source} does not exist, creating it.")
            os.makedirs(zip_source, exist_ok=True)

        zip_res = shutil.make_archive(zip_filepath, "zip", zip_source)
        s3_client.upload_file(zip_res, S3_BUCKET, f"{node_id}/{zip_filename}.zip")

        logger.info(f"Created a snapshot for node {node_id}")
    except Exception as e:
        logger.error(f"Failed to create a snapshot for node {node_id}: {e}")
        return None
    finally:
        zip_res_full = zip_filepath + ".zip"
        if os.path.exists(zip_res_full):
            os.remove(zip_res_full)

    return zip_filename


def recover_snapshot(node_id: str, snapshot_id: str):
    RECOVERY_MODE.set()
    s3_key = f"{node_id}/{snapshot_id}.zip"
    zip_filepath = os.path.join(TEMP_DIR, snapshot_id + ".zip")
    destination_path = os.path.join(WATCH_PATH, node_id)

    try:
        logger.info(f"Downloading snapshot {snapshot_id}...")
        os.makedirs(TEMP_DIR, exist_ok=True)

        s3_client.download_file(S3_BUCKET, s3_key, zip_filepath)

        if os.path.exists(destination_path):
            # Clear directory contents instead of deleting the directory itself
            # to preserve the watchdog watch on the root directory.
            for item in os.listdir(destination_path):
                item_path = os.path.join(destination_path, item)
                try:
                    if os.path.isdir(item_path):
                        shutil.rmtree(item_path)
                    else:
                        os.remove(item_path)
                except Exception as e:
                    logger.error(f"Failed to delete {item_path}: {e}")

        os.makedirs(destination_path, exist_ok=True)
        shutil.unpack_archive(zip_filepath, destination_path)

        logger.info(f"Recovered snapshot {node_id} for node {NODE_ID}")

        return destination_path

    finally:
        if os.path.exists(zip_filepath):
            os.remove(zip_filepath)
        time.sleep(1)
        RECOVERY_MODE.clear()


def periodic_snapshot_worker(interval_seconds: int):
    while True:
        try:
            capture_snapshot(NODE_ID)
        except Exception as e:
            logger.error(f"Could not capture snapshot: {e}")
        time.sleep(interval_seconds)


def monitor_worker():
    handler = FileMonitorHandler(redis_client, s3_client)
    observer = Observer()

    observer.schedule(handler, WATCH_NODE_PATH, recursive=True)
    observer.start()

    logger.info(f"Monitor started on {WATCH_NODE_PATH}")

    handler.ping_online()

    try:
        while True:
            handler.ping_online()
            time.sleep(5)
    except Exception as e:
        logger.error(f"Monitor worker error: {e}")
    finally:
        observer.stop()
        observer.join()


# ======================
# Flask Routes
# ======================
@app.route("/snapshot", methods=["POST"])
def snapshot():
    snapshot_id = capture_snapshot(NODE_ID)
    if not snapshot_id:
        return jsonify({"error": "snapshot_failed"}), 500
    return jsonify(
        {"node_id": NODE_ID, "snapshot_id": snapshot_id, "status": "success"}
    )


@app.route("/restore", methods=["POST"])
def restore():
    data = request.get_json()

    if not data or "node_id" not in data or "snapshot_id" not in data:
        return jsonify({"error": "invalid_request"}), 400

    node_id = data["node_id"]
    snapshot_id = data["snapshot_id"]

    try:
        location = recover_snapshot(node_id, snapshot_id)
        return jsonify(
            {
                "status": "success",
                "node_id": node_id,
                "snapshot_id": snapshot_id,
                "backup_location": location,
            }
        ), 200

    except Exception as e:
        logger.error(f"Recovery failed: {e}")
        return jsonify({"error": "restore_failed"}), 500


# ======================
# Main
# ======================
if __name__ == "__main__":
    from waitress import serve

    # Ensure node directory exists and populate with template if nonexistent
    try:
        template_dir = os.path.join(os.path.dirname(__file__), "template_node_files")
        if not os.path.exists(WATCH_NODE_PATH):
            shutil.copytree(template_dir, WATCH_NODE_PATH)
            logger.info(f"Initialized node directory from template: {WATCH_NODE_PATH}")
    except Exception as e:
        logger.error(f"Could not initialize node directory: {e}")

    # Start monitor thread
    monitor_thread = threading.Thread(target=monitor_worker, daemon=True)
    monitor_thread.start()

    # Start periodic snapshot thread
    snapshot_thread = threading.Thread(
        target=periodic_snapshot_worker, args=(BACKUP_INTERVAL_SECONDS,), daemon=True
    )
    snapshot_thread.start()

    logger.info(f"Starting Client API on port {APP_PORT}")
    serve(app, host="0.0.0.0", port=APP_PORT)
