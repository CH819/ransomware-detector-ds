import logging
import os
import shutil
import time
import uuid

from flask import Flask, jsonify, request

DATA_DIR = "/data"
SNAPSHOT_DIR = "/snapshots"
NODE_ID = os.environ.get("NODE_ID", f"{uuid.uuid4()}")
APP_PORT = os.environ.get("APP_PORT", 5001)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - STORAGE NODE - %(levelname)s - %(message)s\n",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

os.makedirs(SNAPSHOT_DIR, exist_ok=True)


def create_snapshot(snapshot_id):
    """
    Create snapshot by copying content in data folder to snapshot folder under
    given ID.
    """
    snapshot_path = os.path.join(SNAPSHOT_DIR, str(snapshot_id))
    os.makedirs(snapshot_path, exist_ok=True)

    shutil.copy2(DATA_DIR, snapshot_path)
    logger.info(f"Saved snapshot {snapshot_id}")


def recover_snapshot(snapshot_id):
    """
    Recover snapshot by given ID by copying it to data folder.
    """
    snapshot_path = os.path.join(SNAPSHOT_DIR, str(snapshot_id))

    if not os.path.exists(snapshot_path):
        logger.error(f"Cannot recover snapshot {snapshot_id}")
        return False

    if os.path.exists(DATA_DIR):
        shutil.rmtree(DATA_DIR)

    shutil.copytree(snapshot_path, DATA_DIR)
    logger.info(f"Snapshot {snapshot_id} recovered")

    return True


@app.route("/snapshot", methods=["POST"])
def snapshot():
    snapshot_id = request.json["snapshot_id"]
    create_snapshot(snapshot_id)

    return jsonify({"node_id": NODE_ID, "snapshot_id": snapshot_id, "status": "ok"})


@app.route("/restore", methods=["POST"])
def restore():
    snapshot_id = request.json["snapshot_id"]
    success = recover_snapshot(snapshot_id)

    return jsonify(
        {"node_id": NODE_ID, "snapshot_id": snapshot_id, "restored": success}
    )


if __name__ == "__main__":
    app.run(port=APP_PORT)
