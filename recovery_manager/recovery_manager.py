import json
import logging
import os
import shutil
import time
from datetime import datetime

import redis


class RecoveryManager:
    def __init__(self, redis_host="localhost", redis_port=6379):
        self.redis_client = redis.Redis(host=redis_host, port=redis_port, decode_responses=True)
        self.input_stream = "ransomware_alerts"
        self.base_snapshot_path = "./snapshots"
        self.destination_path = "./folder"

        logging.basicConfig(level=logging.INFO, format="%(asctime)s - RECOVERY MANAGER - %(levelname)s - %(message)s\n")
        self.logger = logging.getLogger(__name__)

    def get_most_recent_snapshot_id(self, alert):
        return alert["backup_version_id"]

    def recover_snapshot(self, snapshot_id):
        snapshot_path = os.path.join(self.base_snapshot_path, snapshot_id)

        if os.path.exists(self.destination_path):
            shutil.rmtree(self.destination_path)

        shutil.copytree(snapshot_path, self.destination_path)

        self.logger.info(f"Snapshot {snapshot_id} recovered")

    def run_recovery(self, alert):
        most_recent_clean_snapshot = self.get_most_recent_snapshot_id(alert)

        self.recover_snapshot(most_recent_clean_snapshot)

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
                    if data["recommended_action"] == "ISOLATE_NODE_AND_INITIATE_RECOVERY":
                        self.run_recovery(data)

            except KeyboardInterrupt:
                self.logger.info("Shutting down recovery manager...\n")
                break
            except Exception as e:
                self.logger.error(f"Error: {e}\n")
                time.sleep(1)


if __name__ == "__main__":
    recovery_manager = RecoveryManager()
    recovery_manager.main()
