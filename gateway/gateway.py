import redis
import json
import logging
import time
import os
from datetime import datetime
from enum import Enum

REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))

# Redis Stream names
STREAM_FILE_INFO = "file_info"              # From Monitor (file information)
STREAM_BACKUP_DATA = "backup_data"          # From Backup Service (backup updates)
STREAM_DETECTOR_IN = "detector_in"          # To Detector (file info for analysis)
STREAM_DETECTOR_OUT = "detector_out"        # From Detector (analysis results: ISOLATE/BACKUP)
STREAM_BACKUP_CONTROL = "backup_control"    # To Backup Service (stop backup commands)
STREAM_ADMIN_ALERTS = "admin_alerts"        # To Admin (backup needed notifications)
STREAM_ADMIN_COMMANDS = "admin_commands"    # From Admin (initiate backup commands)
STREAM_RECOVERY_REQUESTS = "recovery_requests"  # To Recovery Manager (which backup?)
STREAM_RECOVERY_RESPONSES = "recovery_responses" # From Recovery Manager (backup location)
STREAM_CLIENT_NOTIFY = "client_notify"      # To Client (final information)


class NodeStatus(Enum):
    HEALTHY = "healthy"
    SUSPICIOUS = "suspicious"  # Needs backup but not isolated
    ISOLATED = "isolated"      # Needs backup and is isolated
    RECOVERING = "recovering"


class Gateway:
    def __init__(self, redis_host=REDIS_HOST, redis_port=REDIS_PORT):
        self.redis = redis.Redis(host=redis_host, port=redis_port, decode_responses=True)
        
        # Node state tracking
        self.node_status = {}           # node_id -> NodeStatus
        self.node_file_events = {}      # node_id -> list of recent file events
        self.node_backup_info = {}      # node_id -> latest backup info from Backup Service
        self.pending_backups = set()    # node_ids waiting for admin to initiate backup
        
        # Logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - GATEWAY - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)
        
        # Consumer groups for scalable processing
        self._init_consumer_groups()

    def _init_consumer_groups(self):
        """Initialize consumer groups for streams that need reliable processing"""
        streams_with_groups = [
            (STREAM_DETECTOR_OUT, "gateway_detector_cg"),
            (STREAM_ADMIN_COMMANDS, "gateway_admin_cg"),
            (STREAM_RECOVERY_RESPONSES, "gateway_recovery_cg")
        ]
        
        for stream, group in streams_with_groups:
            try:
                self.redis.xgroup_create(stream, group, id="0", mkstream=True)
                self.logger.info(f"Created consumer group {group} for {stream}")
            except redis.ResponseError as e:
                if "already exists" not in str(e):
                    raise

    # MESSAGE RECEIVERS (from other services)
    # =========================================================================

    def receive_from_monitor(self, file_info: dict):
        """
        Receive file information from Monitor (running on client).
        Forward to Detector for analysis.
        """
        node_id = file_info.get("node_id")
        file_path = file_info.get("file_path")
        
        self.logger.info(f"📥 Received file info from Monitor [{node_id}]: {file_path}")
        
        # Store for later reference
        if node_id not in self.node_file_events:
            self.node_file_events[node_id] = []
        self.node_file_events[node_id].append(file_info)
        
        # Keep only last 100 events per node
        if len(self.node_file_events[node_id]) > 100:
            self.node_file_events[node_id].pop(0)
        
        # Forward to Detector for analysis
        self._send_to_detector(file_info)
        
        return {"status": "forwarded_to_detector", "node_id": node_id}

    def receive_from_backup_service(self, backup_data: dict):
        """
        Receive backup information from Backup Service.
        Store for when we need to know what backups are available.
        """
        node_id = backup_data.get("node_id")
        backup_version = backup_data.get("backup_version")
        
        self.logger.info(f"💾 Received backup data from Backup Service [{node_id}]: {backup_version}")
        
        # Store backup info for this node
        if node_id not in self.node_backup_info:
            self.node_backup_info[node_id] = []
        
        self.node_backup_info[node_id].append({
            "backup_version": backup_version,
            "timestamp": backup_data.get("timestamp"),
            "file_count": backup_data.get("file_count"),
            "size_bytes": backup_data.get("size_bytes"),
            "location": backup_data.get("location")
        })
        
        # Keep only last 10 backups
        if len(self.node_backup_info[node_id]) > 10:
            self.node_backup_info[node_id].pop(0)
        
        return {"status": "backup_registered", "node_id": node_id}

    def receive_from_detector(self, analysis_result: dict):
        """
        Receive analysis result from Detector.
        Result is either "ISOLATE" or "BACKUP".
        Includes backup_id of the infected file.
        """
        node_id = analysis_result.get("node_id")
        decision = analysis_result.get("decision")  # "ISOLATE" or "BACKUP"
        file_path = analysis_result.get("file_path")
        backup_id = analysis_result.get("backup_id")  # <-- EXTRACT BACKUP ID
        
        self.logger.info(f"🔍 Received analysis from Detector [{node_id}]: {decision} for {file_path}")
        self.logger.info(f"   Backup ID: {backup_id}")
        
        if decision == "ISOLATE":
            self.node_status[node_id] = NodeStatus.ISOLATED
            self.pending_backups.add(node_id)
            
            # Store backup_id for later
            self.node_backup_info[node_id] = {"backup_id": backup_id}
            
            self._stop_backup_service(node_id, reason="infection_detected")
            self._notify_admin_backup_needed(node_id, file_path, analysis_result, backup_id)
            
            self.logger.info(f"🚨 Node {node_id} ISOLATED")
            
        elif decision == "BACKUP":
            self.node_status[node_id] = NodeStatus.SUSPICIOUS
            self.pending_backups.add(node_id)
            
            # Store backup_id for later
            self.node_backup_info[node_id] = {"backup_id": backup_id}
            
            self._notify_admin_backup_needed(node_id, file_path, analysis_result, backup_id)
            
            self.logger.info(f"⚠️ Node {node_id} marked SUSPICIOUS")
        
        return {"status": "processed", "node_id": node_id, "action": decision}

    def receive_from_admin(self, admin_command: dict):
        """
        Receive command from Admin.
        Admin logs in and initiates backup after receiving notification.
        """
        command = admin_command.get("command")  # "INITIATE_BACKUP"
        node_id = admin_command.get("node_id")
        
        self.logger.info(f"👤 Received command from Admin: {command} for {node_id}")
        
        if command == "INITIATE_BACKUP":
            if node_id not in self.pending_backups:
                self.logger.warning(f"Node {node_id} not in pending backups list")
                return {"error": "no_backup_pending"}
            
            # Get the backup_id that was stored earlier
            backup_info = self.node_backup_info.get(node_id, {})
            backup_id = backup_info.get("backup_id")
            
            if not backup_id:
                self.logger.error(f"No backup_id available for node {node_id}")
                return {"error": "no_backup_id"}
            
            # Pass backup_id to Recovery Manager (Recovery Manager decides what to do with it)
            self._request_recovery_manager(node_id, backup_id)
            
            self.pending_backups.discard(node_id)
            
            return {"status": "recovery_requested", "node_id": node_id, "backup_id": backup_id}
        
        else:
            self.logger.warning(f"Unknown admin command: {command}")
            return {"error": "unknown_command"}
        
    def receive_from_recovery_manager(self, recovery_response: dict):
        """
        Receive response from Recovery Manager.
        Contains which file to backup and where it is located.
        """
        node_id = recovery_response.get("node_id")
        backup_location = recovery_response.get("backup_location")
        files_to_restore = recovery_response.get("files_to_restore", [])
        
        self.logger.info(f"📋 Received recovery info from Recovery Manager for {node_id}")
        self.logger.info(f"   Backup location: {backup_location}")
        self.logger.info(f"   Files count: {len(files_to_restore)}")
        
        # Update node status
        self.node_status[node_id] = NodeStatus.RECOVERING
        
        # Send final information to Client
        self._notify_client(node_id, backup_location, files_to_restore)
        
        return {"status": "client_notified", "node_id": node_id}

    # MESSAGE SENDERS (to other services)
    # =========================================================================

    def _send_to_detector(self, file_info: dict):
        """Forward file information to Detector for analysis"""
        message = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            **file_info
        }
        
        self.redis.xadd(STREAM_DETECTOR_IN, message)
        self.logger.debug(f"📤 Sent file info to Detector: {file_info.get('file_path')}")

    def _stop_backup_service(self, node_id: str, reason: str):
        """Send command to Backup Service to stop backing up infected node"""
        cmd = {
            "command": "STOP_BACKUP",
            "node_id": node_id,
            "reason": reason,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
        
        self.redis.xadd(STREAM_BACKUP_CONTROL, cmd)
        self.logger.info(f"🛑 Sent STOP_BACKUP command to Backup Service for {node_id}")

    def _notify_admin_backup_needed(self, node_id: str, file_path: str, analysis: dict, backup_id: str):
        """Notify Admin that a backup is needed for this node"""
        alert = {
            "alert_type": "BACKUP_NEEDED",
            "node_id": node_id,
            "file_path": file_path,
            "threat_level": "HIGH" if analysis.get("decision") == "ISOLATE" else "MEDIUM",
            "risk_score": analysis.get("risk_score"),
            "indicators": analysis.get("indicators"),
            "backup_id": backup_id,  # <-- PASS THROUGH BACKUP ID
            "message": f"Node {node_id} requires backup. File: {file_path}, Backup: {backup_id}",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "action_required": "INITIATE_BACKUP"
        }
        
        self.redis.xadd(STREAM_ADMIN_ALERTS, alert)
        self.logger.info(f"📧 Notified Admin: BACKUP_NEEDED for {node_id} (backup: {backup_id})")

    def _request_recovery_manager(self, node_id: str, backup_id: str):
        """
        Pass backup_id to Recovery Manager.
        Recovery Manager decides which backup to use based on this ID.
        """
        request = {
            "command": "RECOVER",
            "node_id": node_id,
            "backup_id": backup_id,  # <-- JUST PASS THE BACKUP ID
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
        
        self.redis.xadd(STREAM_RECOVERY_REQUESTS, request)
        self.logger.info(f"🔍 Passed backup_id {backup_id} to Recovery Manager for {node_id}")

    def _notify_client(self, node_id: str, backup_location: str, files: list):
        """Send final recovery information to Client"""
        notification = {
            "notification_type": "RECOVERY_INFO",
            "node_id": node_id,
            "backup_location": backup_location,
            "files_to_restore": files,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "message": f"Recovery information for node {node_id}"
        }
        
        self.redis.xadd(STREAM_CLIENT_NOTIFY, notification)
        self.logger.info(f"📤 Sent recovery info to Client for {node_id}")

    # HELPER METHODS
    # =========================================================================

    def _get_latest_backup_info(self, node_id: str):
        """Get the most recent backup info for a node"""
        backups = self.node_backup_info.get(node_id, [])
        return backups[-1] if backups else None

    def get_node_status(self, node_id: str = None):
        """Get status of node(s)"""
        if node_id:
            return {
                "node_id": node_id,
                "status": self.node_status.get(node_id, NodeStatus.HEALTHY).value,
                "pending_backup": node_id in self.pending_backups,
                "latest_backup": self._get_latest_backup_info(node_id)
            }
        
        return {
            node: {
                "status": status.value,
                "pending_backup": node in self.pending_backups
            }
            for node, status in self.node_status.items()
        }

    # MAIN EVENT LOOP
    # =========================================================================

    def run(self):
        """Main event loop - listen to all input streams"""
        self.logger.info("🚀 Gateway started and listening for events...")
        self.logger.info("  Listening on: file_info, backup_data, detector_out, admin_commands, recovery_responses")
        
        while True:
            try:
                # Read from all input streams
                streams = {
                    STREAM_FILE_INFO: "0",           # From Monitor
                    STREAM_BACKUP_DATA: "0",         # From Backup Service
                    STREAM_DETECTOR_OUT: ">",        # From Detector (consumer group)
                    STREAM_ADMIN_COMMANDS: ">",      # From Admin (consumer group)
                    STREAM_RECOVERY_RESPONSES: ">",  # From Recovery Manager (consumer group)
                }
                
                # Block for up to 5 seconds waiting for messages
                messages = self.redis.xread(streams, count=10, block=5000)
                
                for stream_name, msg_list in messages:
                    for msg_id, data in msg_list:
                        
                        # Route to appropriate handler based on stream
                        if stream_name == STREAM_FILE_INFO:
                            self.receive_from_monitor(data)
                            self.redis.xdel(STREAM_FILE_INFO, msg_id)
                            
                        elif stream_name == STREAM_BACKUP_DATA:
                            self.receive_from_backup_service(data)
                            self.redis.xdel(STREAM_BACKUP_DATA, msg_id)
                            
                        elif stream_name == STREAM_DETECTOR_OUT:
                            self.receive_from_detector(data)
                            self.redis.xack(STREAM_DETECTOR_OUT, "gateway_detector_cg", msg_id)
                            
                        elif stream_name == STREAM_ADMIN_COMMANDS:
                            self.receive_from_admin(data)
                            self.redis.xack(STREAM_ADMIN_COMMANDS, "gateway_admin_cg", msg_id)
                            
                        elif stream_name == STREAM_RECOVERY_RESPONSES:
                            self.receive_from_recovery_manager(data)
                            self.redis.xack(STREAM_RECOVERY_RESPONSES, "gateway_recovery_cg", msg_id)

            except KeyboardInterrupt:
                self.logger.info("Shutting down gateway...")
                break
                
            except Exception as e:
                self.logger.error(f"Error in gateway loop: {e}")
                time.sleep(1)


if __name__ == "__main__":
    gateway = Gateway()
    gateway.run()