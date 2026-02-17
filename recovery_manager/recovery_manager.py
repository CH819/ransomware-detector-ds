import json
import logging
import os
import shutil
import time
from datetime import datetime

import redis
import boto3
from botocore.client import Config

REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))
STREAM_NAME_RANSOMWARE_ALERTS = "ransomware_alerts"
SNAPSHOT_DIR = os.environ.get("SNAPSHOT_DIR", "/utils/snapshots")
DESTINATION_DIR = os.environ.get("WATCH_PATH", "/utils/test_files")
TEMP_DIR = "../utils/tmp"
S3_ENDPOINT = os.environ.get("S3_ENDPOINT", "http://localhost:9333")
S3_BUCKET = os.environ.get("S3_BUCKET", "files")
S3_ACCESS_KEY = os.environ.get("S3_ACCESS_KEY")
S3_SECRET_KEY = os.environ.get("S3_SECRET_KEY")


class RecoveryManager:
    def __init__(self, redis_host=REDIS_HOST, redis_port=REDIS_PORT):
        self.redis_client = redis.Redis(host=redis_host, port=redis_port, decode_responses=True)
        self.s3_client = boto3.client(
            "s3",
            aws_access_key_id=S3_ACCESS_KEY,
            aws_secret_access_key=S3_SECRET_KEY,
            endpoint_url=S3_ENDPOINT,
            config=Config(signature_version="s3v4"),
            region_name="us-east-1",
        )
        self.input_stream = STREAM_NAME_RANSOMWARE_ALERTS
        self.base_snapshot_path = SNAPSHOT_DIR
        self.destination_path = DESTINATION_DIR
        self.temp_path = TEMP_DIR

        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - RECOVERY MANAGER - %(levelname)s - %(message)s\n",
        )
        self.logger = logging.getLogger(__name__)

    def get_most_recent_clean_snapshot_name(self, alert):
        infected_backup_id = alert["infected_backup_id"]
        name, node_id, infected_timestamp = infected_backup_id.split("_")

        prefix = f"{node_id}/"

        try:
            response = self.s3_client.list_objects_v2(
                Bucket=S3_BUCKET,
                Prefix=prefix,
            )

            if "Contents" not in response:
                self.logger.error(f"No snapshots found for node {node_id}")
                return None

            snapshots = []

            for obj in response["Contents"]:
                key = obj["Key"]

                if not key.endswith(".zip"):
                    continue

                filename = os.path.basename(key).replace(".zip", "")
                _, snap_node_id, snap_timestamp = filename.split("_")

                if snap_node_id == node_id and snap_timestamp < infected_timestamp:
                    snapshots.append(snap_timestamp)

            if not snapshots:
                self.logger.error("No clean snapshots found before infection time")
                return None

            clean_timestamp = max(snapshots)
            clean_snapshot_name = f"{name}_{node_id}_{clean_timestamp}"

            return clean_snapshot_name

        except Exception as e:
            self.logger.error(f"Failed to retrieve snapshots: {e}")
            return None

    def recover_snapshot(self, node_id, snapshot_id):
        filename = f"/{node_id}/{snapshot_id}"
        zip_filepath = os.path.join(self.temp_path, snapshot_id + ".zip")
        destination_path = os.path.join(self.destination_path, node_id)

        try:
            self.logger.info(f"Recovering snapshot {snapshot_id}...")
            self.s3_client.download_file(S3_BUCKET, filename, zip_filepath)

            if os.path.exists(destination_path):
                self.logger.info(f"Recover {snapshot_id}: removing existing data at {destination_path}...")
                shutil.rmtree(self.destination_path)
            os.makedirs(destination_path, exist_ok=True)

            shutil.unpack_archive(zip_filepath, destination_path)

            self.logger.info(f"Snapshot {snapshot_id} recovered")
        except self.s3_client.exceptions.NoSuchKey:
            self.logger.error(f"Snapshot not found in S3: {filename}")
        except Exception as e:
            self.logger.error(f"Recovery failed: {e}")
        finally:
            if os.path.exists(zip_filepath):
                os.remove(zip_filepath)

    def capture_snapshot(self, node_id):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        zip_filename = f"snapshot_{node_id}_{timestamp}"
        zip_filepath = os.path.join(self.temp_path, zip_filename)
        zip_source = os.path.join(self.destination_path, node_id)

        try:
            if self.temp_path and not os.path.exists(self.temp_path):
                os.makedirs(self.temp_path, exist_ok=True)

            zip_res = shutil.make_archive(zip_filepath, "zip", zip_source)
            self.s3_client.upload_file(zip_res, S3_BUCKET, f"/{node_id}/{zip_filename}")
        except Exception as e:
            self.logger.error(f"Failed to create a snapshot for node {node_id}: {e}")
        finally:
            zip_res = zip_filepath + ".zip"
            if os.path.exists(zip_res):
                os.remove(zip_res)
            self.logger.info(f"Created a snapshot for node {node_id} with timestamp {timestamp}")

    def run_recovery(self, alert):
        most_recent_clean_snapshot = self.get_most_recent_clean_snapshot_name(alert)

        self.recover_snapshot(alert["node_id"], most_recent_clean_snapshot)

    def main(self):
        self.logger.info("Recovery manager started, waiting for events...\n")
        while True:
            try:
                messages = self.redis_client.xread({self.input_stream: "0"}, count=1, block=5000)
                if messages:
                    _stream, msg_list = messages[0]
                    msg_id, data = msg_list[0]
                    self.redis_client.xdel(self.input_stream, msg_id)

                    self.logger.info("Processing alert...")
                    if data["command"] == "RECOVER":
                        self.run_recovery(data["node_id"])

            except KeyboardInterrupt:
                self.logger.info("Shutting down recovery manager...\n")
                break
            except Exception as e:
                self.logger.error(f"Error: {e}\n")
                time.sleep(1)


if __name__ == "__main__":
    recovery_manager = RecoveryManager()
    recovery_manager.main()
