import redis
import logging
import time
import os
import uuid
import boto3
import threading
import json
from typing import Optional
from botocore.client import Config
from datetime import datetime
from enum import Enum
import requests
from dotenv import load_dotenv

load_dotenv()


#REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))
RECOVERY_MANAGER_URL = os.environ.get(
    "RECOVERY_MANAGER_URL", "http://recovery-manager:8000/recover"
)
CLIENT_BASE_URL = os.environ.get("CLIENT_BASE_URL", "http://storage-node:7000")


S3_ENDPOINT = os.environ.get("S3_ENDPOINT", "http://s3:9333")
S3_BUCKET = os.environ.get("S3_BUCKET", "files")
S3_ACCESS_KEY = os.environ.get("S3_ACCESS_KEY")
S3_SECRET_KEY = os.environ.get("S3_SECRET_KEY")

# Stream names
STREAM_FILE_INFO = "file_info"  # From Monitor
STREAM_PING = "ping"  # To Monitor (Heartbeat)
STREAM_DETECTOR_IN = "detector_in"  # To Detector
STREAM_DETECTOR_OUT = "detector_out"  # From Detector
STREAM_BACKUP_CONTROL = "backup_control"  # To Backup Service
STREAM_ADMIN_ALERTS = "admin_alerts"  # To Admin
STREAM_ADMIN_COMMANDS = "admin_commands"  # From Admin
STREAM_RECOVERY_REQUESTS = "recovery_requests"
STREAM_CLIENT_NOTIFY = "client_notify"

# Leader election settings
LEADER_KEY = "gateway:leader"
LEADER_EXPIRY_SECONDS = 10  # Time before failover
HEARTBEAT_INTERVAL_SECONDS = 3  # How often to renew leadership

class NodeStatus(Enum):
    HEALTHY = "healthy"
    SUSPICIOUS = "suspicious"  # backup
    ISOLATED = "isolated"  # isolate and backup
    RECOVERING = "recovering"


class Gateway:
    def __init__(self, redis_host=REDIS_HOST, redis_port=REDIS_PORT, node_id: Optional[str] = None):
        self.gateway_id = node_id or f"gateway-{uuid.uuid4().hex[:8]}"
        self.redis = redis.Redis(host=redis_host, port=redis_port, decode_responses=True)
        
        # Leadership state
        self.is_leader = False
        self.leader_thread: Optional[threading.Thread] = None
        self.shutdown_event = threading.Event()
        
        # Local cache only - authoritative source is Redis
        self._local_node_status_cache = {}
        self._cache_lock = threading.Lock()
        
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - GATEWAY - %(levelname)s - %(message)s",
        )
        self.logger = logging.getLogger(__name__)
        self.logger = logging.LoggerAdapter(self.logger, {"gateway_id": self.gateway_id})

        self._init_consumer_groups()

        self.s3_client = boto3.client(
        "s3",
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY,
        endpoint_url=S3_ENDPOINT,
        config=Config(signature_version="s3v4"),
        region_name="us-east-1",
    )

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

    def _acquire_leadership(self) -> bool:
        """Try to become leader using Redis SET NX with expiry."""
        try:
            acquired = self.redis.set(
                LEADER_KEY,
                self.gateway_id,
                nx=True,
                ex=LEADER_EXPIRY_SECONDS,
            )
            if acquired:
                self.is_leader = True
                self.logger.info(f"BECAME LEADER")
                return True
            else:
                current_leader = self.redis.get(LEADER_KEY)
                if current_leader == self.gateway_id:
                    self.redis.setex(LEADER_KEY, LEADER_EXPIRY_SECONDS, self.gateway_id)
                    self.is_leader = True
                    return True
                self.is_leader = False
                return False
        except redis.RedisError as e:
            self.logger.error(f"Redis error during leader election: {e}")
            return False

    def _renew_leadership(self):
        """Renew leadership TTL while active."""
        if self.is_leader:
            try:
                current = self.redis.get(LEADER_KEY)
                if current == self.gateway_id:
                    self.redis.expire(LEADER_KEY, LEADER_EXPIRY_SECONDS)
                    return True
                else:
                    self.logger.warning("LOST LEADERSHIP")
                    self.is_leader = False
                    return False
            except redis.RedisError as e:
                self.logger.error(f"Failed to renew leadership: {e}")
                self.is_leader = False
                return False
        return False

    def _leader_heartbeat(self):
        """Background thread: maintain leadership or watch for failover."""
        while not self.shutdown_event.is_set():
            if self.is_leader:
                if not self._renew_leadership():
                    self._transition_to_passive()
            else:
                if self._acquire_leadership():
                    self._transition_to_active()
            self.shutdown_event.wait(HEARTBEAT_INTERVAL_SECONDS)

    def _transition_to_active(self):
        """Called when this gateway becomes the active leader."""
        self.logger.info("TRANSITIONING TO ACTIVE MODE")
        self.is_leader = True

    def _transition_to_passive(self):
        """Called when this gateway loses leadership."""
        self.logger.info("TRANSITIONING TO PASSIVE MODE")
        self.is_leader = False
        with self._cache_lock:
            self._local_node_status_cache.clear()

    def _start_leader_election(self):
        """Start the leader election background thread."""
        self.leader_thread = threading.Thread(
            target=self._leader_heartbeat, name="leader-election", daemon=True
        )
        self.leader_thread.start()
        self._acquire_leadership()

    # =========================================================================
    # STATE MANAGEMENT
    # =========================================================================

    def is_node_healthy(self, node_id: str) -> bool:
        """Check if node can process new files (from Redis)."""
        status = self.redis.hget("gateway:node_status", node_id)
        if status is None:
            return True
        return status == NodeStatus.HEALTHY.value

    def get_node_status(self, node_id: str) -> NodeStatus:
        """Get node status from Redis."""
        status = self.redis.hget("gateway:node_status", node_id)
        if status is None:
            return NodeStatus.HEALTHY
        return NodeStatus(status)

    def get_all_node_status(self) -> dict[str, NodeStatus]:
        """Get all node statuses from Redis."""
        statuses = self.redis.hgetall("gateway:node_status")
        return {k: NodeStatus(v) for k, v in statuses.items()}

    def get_nodes_backups(self) -> dict[str, dict]:
        """Get all node backup data from Redis."""
        backups = self.redis.hgetall("gateway:node_backup_info")
        return {k: json.loads(v) for k, v in backups.items()}

    def get_node_snapshots(self, node_id: str) -> list[dict]:
        """Get node snapshots from S3."""
        # Note: You'll need to initialize s3_client in __init__ for this to work
        snapshots = self.s3_client.list_objects_v2(
            Bucket=S3_BUCKET, Prefix=f"/{node_id}"
        )
        res = []

        for obj in snapshots.get("Contents", []):
            snapshot_id = obj["Key"].split("/")[-1]
            
            res.append(
                {
                    "id": snapshot_id,
                    "name": "_".join(snapshot_id.split("_")[0:-1]),
                    "size": obj["Size"],
                }
            )

        return res

    def set_node_status(self, node_id: str, status: NodeStatus, reason: str = ""):
        """Update node status in Redis."""
        old_status = self.get_node_status(node_id)
        self.redis.hset("gateway:node_status", node_id, status.value)
        
        # Log to time-series for audit
        self.redis.xadd(
            "gateway:status_history",
            {
                "node_id": node_id,
                "old_status": old_status.value,
                "new_status": status.value,
                "reason": reason,
                "gateway_id": self.gateway_id,
            },
    )
        self.logger.info(f"Node {node_id}: {old_status.value} -> {status.value} ({reason})")

    def reset_node(self, node_id: str, reason: str = "recovery_complete"):
        """Reset node to HEALTHY after recovery."""
        current_status = self.get_node_status(node_id)
        if current_status == NodeStatus.HEALTHY:
            return {"status": "already_healthy"}
            
        self.set_node_status(node_id, NodeStatus.HEALTHY, reason)
        self.redis.srem("gateway:pending_backups", node_id)
        # REMOVED: clearing node_backup_info (no longer stored)
        
        self.logger.info(f"Node {node_id} reset to HEALTHY ({reason})")
        return {"status": "reset", "from": current_status.value, "to": "healthy"}

    # =========================================================================
    # MESSAGE HANDLERS
    # =========================================================================

    def handle_ping(self, event: dict):
        """Receive ping from Monitor and update node status."""
        if not self.is_leader:
            return {"status": "ignored", "reason": "not_leader"}

        event_type = event.get("event_type")
        node_id = event.get("node_id")

        if event_type == "ONLINE":
            # Check if this is a new node (no status in Redis yet)
            existing_status = self.redis.hget("gateway:node_status", node_id)
            if existing_status is None:
                self.logger.info(f"New node detected: {node_id}")
                # Initialize as HEALTHY
                self.set_node_status(node_id, NodeStatus.HEALTHY, "first_online")
            return {"status": "online_ack", "node_id": node_id}

    def handle_monitor_event(self, event: dict):
        """Receive file from Monitor. Filter if node not HEALTHY."""
        if not self.is_leader:
            return {"status": "ignored", "reason": "not_leader"}
            
        node_id = event.get("node_id")
        file_path = event.get("file_path")
        
        if not self.is_node_healthy(node_id):
            current = self.get_node_status(node_id).value
            self.logger.warning(f"DROPPED [{node_id}]: {file_path} (status: {current})")
            return {"status": "dropped", "node_id": node_id, "reason": current}
        
        # Store event history in Redis (not local dict)
        event_key = f"gateway:events:{node_id}"
        self.redis.lpush(event_key, json.dumps(event))
        self.redis.ltrim(event_key, 0, 99)  # Keep last 100
        
        # Forward to Detector
        self.redis.xadd(STREAM_DETECTOR_IN, {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            **event
        })
        self.logger.info(f"[{node_id}] -> Detector: {file_path}")
        return {"status": "forwarded", "node_id": node_id}

    def handle_detector_result(self, result: dict):
        """Receive analysis from Detector. Set status, trigger actions."""
        if not self.is_leader:
            return {"status": "ignored", "reason": "not_leader"}
            
        node_id = result.get("node_id")
        decision = result.get("decision")
        file_path = result.get("file_path")
        
        if not self.is_node_healthy(node_id):
            self.logger.warning(f"Late result for [{node_id}], ignoring")
            return {"status": "ignored", "reason": "already_processed"}
        
        self.logger.info(f"[{node_id}] Decision: {decision} for {file_path}")
        
        if decision == "ISOLATE":
            self.set_node_status(node_id, NodeStatus.ISOLATED, "high_risk_detected")
            self.redis.sadd("gateway:pending_backups", node_id)
            self._stop_backup(node_id)
            self._alert_admin(node_id, file_path, result, "HIGH")  
            
        elif decision == "BACKUP":
            self.set_node_status(node_id, NodeStatus.SUSPICIOUS, "medium_risk_detected")
            self.redis.sadd("gateway:pending_backups", node_id)
            # REMOVED: storing backup_id
            self._alert_admin(node_id, file_path, result, "MEDIUM") 

        elif decision == "SAFE":
            pass
                
        return {"status": "processed", "decision": decision}

    def handle_admin_command(self, cmd: dict):
        """Handle commands from Admin."""
        if not self.is_leader:
            return {"status": "ignored", "reason": "not_leader"}
            
        command = cmd.get("command")
        node_id = cmd.get("node_id")
        
        if command == "INITIATE_BACKUP":
            return self.recover_node(node_id)
            
        elif command == "RESET":
            return self.reset_node(node_id, "manual_reset")
            
        return {"error": "unknown_command"}

    def recover_node(self, node_id: str):
        """Recover node from snapshot via HTTP call to Recovery Manager."""
        if not self.is_leader:
            return {"error": "not_leader"}

        is_pending = self.redis.sismember("gateway:pending_backups", node_id)
        if not is_pending:
            return {"error": "no_backup_pending"}

        self.set_node_status(node_id, NodeStatus.RECOVERING, "recovery_started")

        try:
            recovery_response = requests.post(
                RECOVERY_MANAGER_URL,
                json={"node_id": node_id}, 
                timeout=10,
            )

            if recovery_response.status_code != 200:
                self.logger.error(f"Failed to get snapshot for node {node_id}")
                return {"error": "failed_to_get_snapshot"}

            rm_data = recovery_response.json()
            if rm_data.get("status") != "success":
                self.logger.error(f"No clean snapshot for node {node_id}")
                self.set_node_status(node_id, NodeStatus.ISOLATED, "no_clean_snapshot")
                return {"error": "no_clean_snapshot"}

            snapshot_id = rm_data["snapshot_id"]
            self.logger.info(f"Clean snapshot found for node {node_id}: {snapshot_id}")

            client_response = requests.post(
                f"{CLIENT_BASE_URL}/restore",
                json={"node_id": node_id, "snapshot_id": snapshot_id},
                timeout=60,
            )

            if client_response.status_code != 200:
                self.set_node_status(node_id, NodeStatus.ISOLATED, "client_restore_failed")
                return {"error": "client_restore_failed"}

            self.logger.info(f"Client restore successful for node {node_id}")
            self.reset_node(node_id, "recovery_complete")
            self.redis.srem("gateway:pending_backups", node_id)
            return {"status": "success"}

        except requests.RequestException as e:
            self.logger.error(f"HTTP communication failed: {e}")
            self.set_node_status(node_id, NodeStatus.ISOLATED, "http_failure")
            return {"error": "communication_failure"}

    # =========================================================================
    # HELPERS
    # =========================================================================

    def _stop_backup(self, node_id: str):
        self.redis.xadd(
            STREAM_BACKUP_CONTROL,
            {
                "command": "STOP_BACKUP",
                "node_id": node_id,
                "timestamp": datetime.utcnow().isoformat() + "Z",
            },
        )

    def _alert_admin(self, node_id: str, file_path: str, result: dict, level: str):
        self.redis.xadd(STREAM_ADMIN_ALERTS, {
            "alert_type": "BACKUP_NEEDED",
            "node_id": node_id,
            "file_path": file_path,
            "threat_level": level,
            "risk_score": result.get("risk_score"),
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "gateway_id": self.gateway_id,
        })
    # =========================================================================
    # MAIN LOOP
    # =========================================================================

    def run(self):
        self.logger.info(f"Gateway {self.gateway_id} starting...")
        
        # Start leader election
        self._start_leader_election()
        time.sleep(1)  # Wait for initial election
        self.logger.info(f"Initial state: leader={self.is_leader}")

        # Non-group streams (added STREAM_PING)
        simple_streams = {STREAM_FILE_INFO: "0", STREAM_PING: "0"}
        
        # Consumer group streams 
        group_streams = {
            STREAM_DETECTOR_OUT: "gateway_detector_cg",
            STREAM_ADMIN_COMMANDS: "gateway_admin_cg",
        }
        
        while True:
            try:
                # Only process if leader
                if not self.is_leader:
                    self.shutdown_event.wait(1)
                    continue

                # 1. Read from Monitor and Ping
                messages = self.redis.xread(simple_streams, count=10, block=100)
                for stream, msgs in messages:
                    for msg_id, data in msgs:
                        if stream == STREAM_PING:
                            self.handle_ping(data) 
                        elif stream == STREAM_FILE_INFO:
                            self.handle_monitor_event(data)
                        # Update position
                        simple_streams[stream] = msg_id
                
                # 2. Read from Detector, Admin 
                for stream, group in group_streams.items():
                    messages = self.redis.xreadgroup(
                        group, self.gateway_id, {stream: ">"}, count=10, block=100
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
                self.shutdown_event.set()
                if self.is_leader:
                    self.redis.delete(LEADER_KEY)
                break
            except Exception as e:
                self.logger.error(f"Error: {e}")
                time.sleep(1)
        
        if self.leader_thread:
            self.leader_thread.join(timeout=5)

if __name__ == "__main__":
    import sys
    node_id = sys.argv[1] if len(sys.argv) > 1 else None
    Gateway(node_id=node_id).run()
