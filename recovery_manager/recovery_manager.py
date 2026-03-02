import logging
import os

import boto3
from botocore.client import Config
from dotenv import load_dotenv
from flask import Flask, jsonify, request
from pythonjsonlogger import jsonlogger

load_dotenv()


S3_ENDPOINT = os.environ.get("S3_ENDPOINT", "http://localhost:9333")
S3_BUCKET = os.environ.get("S3_BUCKET", "files")
S3_ACCESS_KEY = os.environ.get("S3_ACCESS_KEY")
S3_SECRET_KEY = os.environ.get("S3_SECRET_KEY")
PORT = os.environ.get("RECOVERY_MANAGER_PORT", 6000)

LOG_FILE = os.environ.get("LOG_FILE", "/logs/recovery_manager.log")

# Logger config
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

file_handler = logging.FileHandler(LOG_FILE)
file_handler.setLevel(logging.INFO)

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)

formatter = jsonlogger.JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")

file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)

logger.addHandler(file_handler)
logger.addHandler(console_handler)

logger.propagate = False
# ---


app = Flask(__name__)

s3_client = boto3.client(
    "s3",
    aws_access_key_id=S3_ACCESS_KEY,
    aws_secret_access_key=S3_SECRET_KEY,
    endpoint_url=S3_ENDPOINT,
    config=Config(signature_version="s3v4"),
    region_name="us-east-1",
)


def get_timestamp_from_backup_id(backup_id: str):
    return int(backup_id.split("_")[-1])


def get_most_recent_clean_snapshot_name(node_id: str, infection_timestamp: int):
    """
    Get the most recent clean snapshot name by searching the last clean snapshot
    saved in S3 before the time of detection.
    All snapshots saved in S3 are listed according to creation timestamp and then
    the most recent one before attack is chosen.

    Args:
        node_id: ID of the node for which the snapshot si requested.
        infection_timestamp: time at which ransomware attack was detected.

    Returns:
        most recent clean snapshot name, or None when search fails.
    """
    try:
        prefix = f"{node_id}/"

        try:
            limit_timestamp = int(infection_timestamp) - 10000
        except (TypeError, ValueError):
            logger.error(f"Invalid infection_timestamp: {infection_timestamp}", exc_info=True)
            return None

        response = s3_client.list_objects_v2(
            Bucket=S3_BUCKET,
            Prefix=prefix,
        )

        if "Contents" not in response:
            return None

        snapshots = []

        for obj in response["Contents"]:
            key = obj["Key"]

            if not key.endswith(".zip"):
                continue

            filename = os.path.basename(key).replace(".zip", "")
            _, snap_node_id, snap_timestamp_string = filename.split("_")
            snap_timestamp = int(snap_timestamp_string)

            if snap_node_id == node_id and snap_timestamp < limit_timestamp:
                snapshots.append((snap_timestamp, filename))

        if not snapshots:
            return None

        # Sort by timestamp descending and take the first one
        snapshots.sort(key=lambda x: x[0], reverse=True)
        return snapshots[0][1]

    except Exception as e:
        logger.error(f"Failed to retrieve snapshot: {e}", exc_info=True)
        return None


@app.route("/recover", methods=["POST"])
def recover():
    """Endpoint to get the most recent clean snapshot, requested by the Gateway"""
    data = request.get_json()

    if not data or "node_id" not in data or "infection_timestamp" not in data:
        return jsonify({"error": "Invalid request"}), 400

    node_id = data["node_id"]
    infection_timestamp = data["infection_timestamp"]

    logger.info("Received recovery lookup for node", extra={"node_id": node_id})

    snapshot_name = get_most_recent_clean_snapshot_name(node_id, infection_timestamp)

    if not snapshot_name:
        return jsonify({"error": "No clean snapshot found"})
    logger.info(f"Clean snapshot found for node", extra={"node_id": node_id, "snapshot_name": snapshot_name})

    return jsonify(
        {
            "status": "success",
            "node_id": node_id,
            "snapshot_id": snapshot_name,
        }
    )


if __name__ == "__main__":
    from waitress import serve

    logger.info("Starting recovery server")
    serve(app, host="0.0.0.0", port=PORT)
