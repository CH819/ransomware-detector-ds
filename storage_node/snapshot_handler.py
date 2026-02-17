import logging
import os
import shutil
import datetime
import uuid
import threading
import time

from flask import Flask, jsonify, request

import boto3
from botocore.client import Config


DESTINATION_DIR = os.environ.get("WATCH_PATH", "/utils/test_files")
TEMP_DIR = "../utils/tmp"
S3_ENDPOINT = os.environ.get("S3_ENDPOINT", "http://localhost:9333")
S3_BUCKET = os.environ.get("S3_BUCKET", "files")
S3_ACCESS_KEY = os.environ.get("S3_ACCESS_KEY")
S3_SECRET_KEY = os.environ.get("S3_SECRET_KEY")
NODE_ID = os.environ.get("NODE_ID", f"{uuid.uuid4()}")
APP_PORT = os.environ.get("APP_PORT", 5001)
BACKUP_INTERVAL_SECONDS = int(os.environ.get("BACKUP_INTERVAL", 10))


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - STORAGE NODE - %(levelname)s - %(message)s\n",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

s3_client = boto3.client(
    "s3",
    aws_access_key_id=S3_ACCESS_KEY,
    aws_secret_access_key=S3_SECRET_KEY,
    endpoint_url=S3_ENDPOINT,
    config=Config(signature_version="s3v4"),
    region_name="us-east-1",
)


def capture_snapshot(node_id):
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_filename = f"snapshot_{node_id}_{timestamp}"
    zip_filepath = os.path.join(TEMP_DIR, zip_filename)
    zip_source = os.path.join(DESTINATION_DIR, node_id)

    try:
        os.makedirs(TEMP_DIR, exist_ok=True)

        zip_res = shutil.make_archive(zip_filepath, "zip", zip_source)
        s3_client.upload_file(zip_res, S3_BUCKET, f"{node_id}/{zip_filename}.zip")

    except Exception as e:
        logger.error(f"Failed to create a snapshot for node {node_id}: {e}")

    finally:
        zip_res = zip_filepath + ".zip"
        if os.path.exists(zip_res):
            os.remove(zip_res)

    logger.info(f"Created a snapshot for node {node_id}")
    return zip_filename


def recover_snapshot(node_id: str, snapshot_id: str):
    s3_key = f"{node_id}/{snapshot_id}.zip"
    zip_filepath = os.path.join(TEMP_DIR, snapshot_id + ".zip")
    destination_path = os.path.join(DESTINATION_DIR, node_id)

    try:
        logger.info(f"Downloading snapshot {snapshot_id}...")
        os.makedirs(TEMP_DIR, exist_ok=True)

        s3_client.download_file(S3_BUCKET, s3_key, zip_filepath)

        if os.path.exists(destination_path):
            shutil.rmtree(destination_path)

        os.makedirs(destination_path, exist_ok=True)
        shutil.unpack_archive(zip_filepath, destination_path)

        logger.info(f"Recovery completed for {node_id}")

        return destination_path

    finally:
        if os.path.exists(zip_filepath):
            os.remove(zip_filepath)


def save_snapshot(interval_seconds: int):
    while True:
        try:
            capture_snapshot(NODE_ID)
        except Exception as e:
            logger.error(f"Could not capture snapshot: {e}")
        time.sleep(interval_seconds)


@app.route("/snapshot", methods=["POST"])
def snapshot():
    snapshot_id = capture_snapshot(NODE_ID)
    return jsonify({"node_id": NODE_ID, "snapshot_id": snapshot_id, "status": "success"})


@app.route("/restore", methods=["POST"])
def restore():
    data = request.get_json()

    if not data or "node_id" not in data or "snapshot_id" not in data:
        return jsonify({"error": "invalid_request"}), 400

    node_id = data["node_id"]
    snapshot_id = data["snapshot_id"]

    try:
        location = recover_snapshot(node_id, snapshot_id)
        return jsonify({
            "status": "success",
            "node_id": node_id,
            "snapshot_id": snapshot_id,
            "backup_location": location
        }), 200

    except Exception as e:
        logger.error(f"Recovery failed: {e}")
        return jsonify({"error": "restore_failed"}), 500


if __name__ == "__main__":
    backup_thread = threading.Thread(target=save_snapshot, args=(BACKUP_INTERVAL_SECONDS,), daemon=True)
    backup_thread.start()

    app.run(port=APP_PORT)
