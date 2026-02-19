import logging
import os

import boto3
from botocore.client import Config
from flask import Flask, request, jsonify

S3_ENDPOINT = os.environ.get("S3_ENDPOINT", "http://localhost:9333")
S3_BUCKET = os.environ.get("S3_BUCKET", "files")
S3_ACCESS_KEY = os.environ.get("S3_ACCESS_KEY")
S3_SECRET_KEY = os.environ.get("S3_SECRET_KEY")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - RECOVERY MANAGER - %(levelname)s - %(message)s\n",
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


def get_most_recent_clean_snapshot_name(node_id, infected_backup_id):
    try:
        name, _, infected_timestamp = infected_backup_id.split("_")
        prefix = f"{node_id}/"

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
            _, snap_node_id, snap_timestamp = filename.split("_")

            if snap_node_id == node_id and int(snap_timestamp) < int(infected_timestamp):
                snapshots.append(snap_timestamp)

        if not snapshots:
            return None

        clean_timestamp = max(snapshots)
        clean_snapshot_name = f"{name}_{node_id}_{clean_timestamp}"
        return clean_snapshot_name

    except Exception as e:
        logger.error(f"Failed to retrieve snapshot: {e}")
        return None


# TODO: remove infected backups


@app.route("/recover", methods=["POST"])
def recover():
    data = request.get_json()

    if not data or "node_id" not in data or "infected_backup_id" not in data:
        return jsonify({"error": "Invalid request"}), 400

    node_id = data["node_id"]
    infected_backup_id = data["infected_backup_id"]

    logger.info(f"Received recovery lookup for node {node_id}")

    snapshot_name = get_most_recent_clean_snapshot_name(node_id, infected_backup_id)

    if not snapshot_name:
        return jsonify({"error": "No clean snapshot found"})

    return jsonify(
        {
            "status": "success",
            "node_id": node_id,
            "snapshot_id": snapshot_name,
        }
    )


if __name__ == "__main__":
    app.run(port=8000)
