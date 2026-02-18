import redis
import logging
import time
import os
import boto3
from botocore.client import Config
from datetime import datetime
from enum import Enum
import requests

REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))
RECOVERY_MANAGER_URL = os.environ.get(
    "RECOVERY_MANAGER_URL",
    "http://recovery-manager:8000/recover"
)
CLIENT_BASE_URL = os.environ.get("CLIENT_BASE_URL", "http://storage-node:5001")


S3_ENDPOINT = os.environ.get("S3_ENDPOINT", "http://localhost:9333")
S3_BUCKET = os.environ.get("S3_BUCKET", "files")
S3_ACCESS_KEY = os.environ.get("S3_ACCESS_KEY")
S3_SECRET_KEY = os.environ.get("S3_SECRET_KEY")

# Stream names
STREAM_FILE_INFO = "file_info"              # From Monitor
STREAM_PING = "ping"                        # To Monitor (Heartbeat)
STREAM_DETECTOR_IN = "detector_in"          # To Detector
STREAM_DETECTOR_OUT = "detector_out"        # From Detector
STREAM_BACKUP_CONTROL = "backup_control"    # To Backup Service
STREAM_ADMIN_ALERTS = "admin_alerts"        # To Admin
STREAM_ADMIN_COMMANDS = "admin_commands"    # From Admin
STREAM_RECOVERY_REQUESTS = "recovery_requests"
STREAM_CLIENT_NOTIFY = "client_notify"

class NodeStatus(Enum):
    HEALTHY = "healthy"
    SUSPICIOUS = "suspicious" # backup
    ISOLATED = "isolated" # isolate and backup
    RECOVERING = "recovering"


class Gateway:
    def __init__(self, redis_host=REDIS_HOST, redis_port=REDIS_PORT):
        self.redis = redis.Redis(host=redis_host, port=redis_port, decode_responses=True)
        self.s3_client = boto3.client(
            "s3",
            aws_access_key_id=S3_ACCESS_KEY,
            aws_secret_access_key=S3_SECRET_KEY,
            endpoint_url=S3_ENDPOINT,
            config=Config(signature_version="s3v4"),
            region_name="us-east-1",
        )

        # Node state
        self.node_status = {}           # node_id -> NodeStatus
        self.node_events = {}           # node_id -> list of recent events
        self.pending_backups = set()    # Nodes waiting for admin
        self.node_backup_info = {}      # node_id -> {infected_backup_id: str} 
        
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - GATEWAY - %(levelname)s - %(message)s",
        )
        self.logger = logging.getLogger(__name__)
        
        self._init_consumer_groups()

    def _init_consumer_groups(self):
        groups = [
            (STREAM_DETECTOR_OUT, "gateway_detector_cg"),
            (STREAM_ADMIN_COMMANDS, "gateway_admin_cg"),
        ]
        for stream, group in groups:
            try:
                self.redis.xgroup_create(stream, group, id="0", mkstream=True)
            except redis.ResponseError as e:
                if "already exists" not in str(e):
                    raise


    # =========================================================================
    # STATE MANAGEMENT
    # =========================================================================

    def is_node_healthy(self, node_id: str) -> bool:
        """Check if node can process new files."""
        return self.node_status.get(node_id, NodeStatus.HEALTHY) == NodeStatus.HEALTHY

    def get_node_status(self, node_id: str) -> NodeStatus:
        """Get node status."""
        return self.node_status.get(node_id, NodeStatus.HEALTHY)

    def get_all_node_status(self) -> dict[str, NodeStatus]:
        """Get all node statuses."""
        return self.node_status
    
    def get_nodes_backups(self) -> dict[str, dict]:
        """Get all node backup data."""
        return self.node_backup_info

    def get_node_snapshots(self, node_id: str) -> dict[str, dict]:
        """Get node snapshots."""
        infected_backup_id = self.node_backup_info.get(node_id, {}).get("infected_backup_id")
        if infected_backup_id == "none":
            infected_backup_id = None
        infected_backup_time = self._get_timestamp_from_backup_id(infected_backup_id) if infected_backup_id else None
        snapshots = self.s3_client.list_objects_v2(Bucket=S3_BUCKET, Prefix=f"/{node_id}")
        res = []

        for obj in snapshots.get("Contents", []):
            snapshot_id = obj["Key"].split("/")[-1]
            snapshot_time = self._get_timestamp_from_backup_id(snapshot_id)
            if infected_backup_id and snapshot_time >= infected_backup_time:
                break

            res.append({
                "id": snapshot_id,
                "name": "_".join(snapshot_id.split("_")[0:-1]),
                "timestamp": snapshot_time,
                "size": obj["Size"]
            })

        return {
            "snapshots": res,
            "infected_backup_id": infected_backup_id,
            "infected_backup_time": infected_backup_time
        }

    def set_node_status(self, node_id: str, status: NodeStatus, reason: str = ""):
        """Update node status."""
        old_status = self.node_status.get(node_id, NodeStatus.HEALTHY)
        self.node_status[node_id] = status
        self.logger.info(f"Node {node_id}: {old_status.value} -> {status.value} ({reason})")

    def reset_node(self, node_id: str, reason: str = "recovery_complete"):
        """Reset node to HEALTHY after recovery."""
        if node_id in self.node_status:
            old_status = self.node_status[node_id].value
            self.node_status[node_id] = NodeStatus.HEALTHY
            self.pending_backups.discard(node_id)
            self.node_backup_info.pop(node_id, None)  # Clear stored backup ID
            self.logger.info(f"Node {node_id} reset to HEALTHY ({reason})")
            return {"status": "reset", "from": old_status, "to": "healthy"}
        return {"error": "node_not_found"}

    # =========================================================================
    # MESSAGE HANDLERS
    # =========================================================================

    def handle_ping(self, event: dict):
        """Receive ping from Monitor. Update node status."""
        event_type = event.get("event_type")
        node_id = event.get("node_id")

        if event_type == "ONLINE" and node_id not in self.node_status:
            self.set_node_status(node_id, NodeStatus.HEALTHY, "online_heartbeat")
            return {"status": "online_ack", "node_id": node_id}

    def handle_monitor_event(self, event: dict):
        """Receive file from Monitor. Filter if node not HEALTHY."""
        node_id = event.get("node_id")
        file_path = event.get("file_path")
        
        if not self.is_node_healthy(node_id):
            current = self.node_status.get(node_id, NodeStatus.HEALTHY).value
            self.logger.warning(f"DROPPED [{node_id}]: {file_path} (status: {current})")
            return {"status": "dropped", "node_id": node_id, "reason": current}
        
        # Store event history
        if node_id not in self.node_events:
            self.node_events[node_id] = []
        self.node_events[node_id].append(event)
        if len(self.node_events[node_id]) > 100:
            self.node_events[node_id].pop(0)
        
        # Forward to Detector
        self.redis.xadd(STREAM_DETECTOR_IN, {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            **event
        })
        self.logger.info(f"[{node_id}] -> Detector: {file_path}")
        return {"status": "forwarded", "node_id": node_id}

    def handle_detector_result(self, result: dict):
        """Receive analysis from Detector. Set status, trigger actions."""
        node_id = result.get("node_id")
        decision = result.get("decision")
        file_path = result.get("file_path")
        backup_id = result.get("infected_backup_id")
        
        # Ignore if node already processed
        if not self.is_node_healthy(node_id):
            self.logger.warning(f"Late result for [{node_id}], ignoring")
            return {"status": "ignored", "reason": "already_processed"}
        
        self.logger.info(f"[{node_id}] Decision: {decision} for {file_path}")
        
        if decision == "ISOLATE":
            self.set_node_status(node_id, NodeStatus.ISOLATED, "high_risk_detected")
            self.pending_backups.add(node_id)
            self.node_backup_info[node_id] = {"infected_backup_id": backup_id}
            self._stop_backup(node_id)
            self._alert_admin(node_id, file_path, result, backup_id, "HIGH")
            
        elif decision == "BACKUP":
            self.set_node_status(node_id, NodeStatus.SUSPICIOUS, "medium_risk_detected")
            self.pending_backups.add(node_id)
            self.node_backup_info[node_id] = {"infected_backup_id": backup_id}
            self._alert_admin(node_id, file_path, result, backup_id, "MEDIUM")

        elif decision == "SAFE":
            pass  # Stay HEALTHY
            
        return {"status": "processed", "decision": decision}

    def handle_admin_command(self, cmd: dict):
        """Handle commands from Admin."""
        command = cmd.get("command")
        node_id = cmd.get("node_id")

        if command == "INITIATE_BACKUP":
            if node_id not in self.pending_backups:
                return {"error": "no_backup_pending"}

            infected_backup_id = self.node_backup_info.get(node_id, {}).get("infected_backup_id")

            if not infected_backup_id:
                return {"error": "no_backup_id_stored"}

            self.set_node_status(node_id, NodeStatus.RECOVERING, "recovery_started")

            try:
                recovery_response = requests.post(
                    RECOVERY_MANAGER_URL,
                    json={
                        "node_id": node_id,
                        "infected_backup_id": infected_backup_id,
                    },
                    timeout=10
                )

                if recovery_response.status_code != 200:
                    self.logger.error("Failed to get snapshot is for node {node_id}")

                rm_data = recovery_response.json()

                if rm_data.get("status") != "success":
                    self.logger.error("No clean snapshot for node {node_id}")

                snapshot_id = rm_data["snapshot_id"]
                self.logger.info(f"Clean snapshot found for node {node_id}: {snapshot_id}")

                client_response = requests.post(
                    f"{CLIENT_BASE_URL}/restore",
                    json={
                        "node_id": node_id,
                        "snapshot_id": snapshot_id,
                    },
                    timeout=60
                )

                if client_response.status_code != 200:
                    self.set_node_status(node_id, NodeStatus.ISOLATED, "client_restore_failed")
                    return {"error": "client_restore_failed"}

                self.logger.info(f"Client restore successful for node {node_id}")

                self.reset_node(node_id, "recovery_complete")
                self.pending_backups.discard(node_id)

            except requests.RequestException as e:
                self.logger.error(f"HTTP communication failed: {e}")
                self.set_node_status(node_id, NodeStatus.ISOLATED, "http_failure")
                return {"error": "communication_failure"}

        elif command == "RESET":
            return self.reset_node(node_id, "manual_reset")
            
        return {"error": "unknown_command"}

    def handle_recovery_response(self, response: dict):
        """Recovery complete. Reset node to HEALTHY."""
        node_id = response.get("node_id")
        backup_location = response.get("backup_location")
        
        self.logger.info(f"Recovery complete for [{node_id}]: {backup_location}")
        
        # Notify client
        self.redis.xadd(STREAM_CLIENT_NOTIFY, {
            "notification_type": "RECOVERY_INFO",
            "node_id": node_id,
            "backup_location": backup_location,
            "files_to_restore": response.get("files_to_restore", []),
            "timestamp": datetime.utcnow().isoformat() + "Z"
        })
        
        # Reset to HEALTHY
        self.reset_node(node_id, "recovery_complete")
        
        return {"status": "complete"}

    def recover_node(self, node_id: str, snapshot_id: str):
        """Recover node from snapshot."""
        self.set_node_status(node_id, NodeStatus.RECOVERING, "recovery_started")
        self.redis.xadd(STREAM_RECOVERY_REQUESTS, {
            "command": "RECOVER",
            "node_id": node_id,
            "backup_version_id": snapshot_id,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        })
        self.pending_backups.discard(node_id)
        return {"status": "recovery_requested"}

    # =========================================================================
    # HELPERS
    # =========================================================================

    def _stop_backup(self, node_id: str):
        self.redis.xadd(STREAM_BACKUP_CONTROL, {
            "command": "STOP_BACKUP",
            "node_id": node_id,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        })

    def _alert_admin(self, node_id: str, file_path: str, result: dict, backup_id: str, level: str):
        self.redis.xadd(STREAM_ADMIN_ALERTS, {
            "alert_type": "BACKUP_NEEDED",
            "node_id": node_id,
            "file_path": file_path,
            "threat_level": level,
            "risk_score": result.get("risk_score"),
            "infected_backup_id": backup_id,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        })

    def _get_timestamp_from_backup_id(self, backup_id: str):
        return datetime.fromtimestamp(int(backup_id.split("_")[-1]))

    # =========================================================================
    # MAIN LOOP
    # =========================================================================

    def run(self):
        self.logger.info("Gateway started")
        
        # Non-group streams
        simple_streams = {STREAM_FILE_INFO: "0", STREAM_PING: "0"}
        
        # Consumer group streams
        group_streams = {
            STREAM_DETECTOR_OUT: "gateway_detector_cg",
            STREAM_ADMIN_COMMANDS: "gateway_admin_cg",
        }
        
        while True:
            try:
                # 1. Read from Monitor
                messages = self.redis.xread(simple_streams, count=10, block=100)
                for stream, msgs in messages:
                    for msg_id, data in msgs:
                        if stream == STREAM_PING:
                            self.handle_ping(data)
                            self.redis.xdel(STREAM_PING, msg_id)
                            simple_streams[STREAM_PING] = msg_id
                        elif stream == STREAM_FILE_INFO:
                            self.handle_monitor_event(data)
                            self.redis.xdel(STREAM_FILE_INFO, msg_id)
                            simple_streams[STREAM_FILE_INFO] = msg_id
                
                # 2. Read from Detector, Admin, Recovery
                for stream, group in group_streams.items():
                    messages = self.redis.xreadgroup(
                        group, "gateway", {stream: ">"}, count=10, block=100
                    )
                    for _, msgs in messages:
                        for msg_id, data in msgs:
                            if stream == STREAM_DETECTOR_OUT:
                                self.handle_detector_result(data)
                            elif stream == STREAM_ADMIN_COMMANDS:
                                self.handle_admin_command(data)
                            self.redis.xack(stream, group, msg_id)
                            
            except KeyboardInterrupt:
                self.logger.info("Shutting down gateway...")
                break
            except Exception as e:
                self.logger.error(f"Error: {e}")
                time.sleep(1)


if __name__ == "__main__":
    Gateway().run()