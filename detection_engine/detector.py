import redis
import json
import logging
import time
import os
from datetime import datetime

REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))

# Redis Stream names
STREAM_GATEWAY_EVENTS = "gateway_events"      # FROM Gateway (file events to analyze)
STREAM_DETECTOR_RESULTS = "detector_results"  # TO Gateway (analysis results)


class RansomwareDetector:
    def __init__(self, detector_id=None, redis_host=REDIS_HOST, redis_port=REDIS_PORT):
        self.detector_id = detector_id or f"detector-{os.getpid()}"
        self.redis_client = redis.Redis(host=redis_host, port=redis_port, decode_responses=True)
        
        # Input: events from Gateway, Output: results back to Gateway
        self.input_stream = STREAM_GATEWAY_EVENTS
        self.output_stream = STREAM_DETECTOR_RESULTS
        
        # Local tracking
        self.event_history = {}
        self.processed_count = 0
        
        # Setup logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - DETECTOR[%(detector_id)s] - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)
        
        # Register with Gateway
        self._register()
        
        self.logger.info(f"Detector {self.detector_id} started, listening on {self.input_stream}")

    def _register(self):
        """Register this detector with the Gateway"""
        reg = {
            "event": "DETECTOR_REGISTERED",
            "detector_id": self.detector_id,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "status": "online"
        }
        self.redis_client.xadd("detector_registrations", reg)
        self.logger.info(f"Registered with Gateway")

    def check_file_content_indicators(self, file_path):
        """Check for ransomware indicators in file path/name"""
        indicators = []
        file_lower = file_path.lower()
        
        # Ransom note patterns
        ransom_patterns = ['readme_to_decrypt', 'how_to_decrypt', 'decrypt_instructions',
                          'ransom_note', 'recover_files', 'unlock_files',
                          '_readme', '_decrypt', '_recover', '_unlock']
        for pat in ransom_patterns:
            if pat in file_lower:
                indicators.append(f'ransom_pattern:{pat}')
        
        # Encrypted file extensions
        encrypted_exts = ['.locked', '.encrypted', '.crypt', '.crypted', '.enc']
        for ext in encrypted_exts:
            if file_lower.endswith(ext):
                indicators.append(f'encrypted_ext:{ext}')
                
        return indicators

    def analyze_event(self, event):
        """
        Analyze file event and return risk assessment.
        Returns: (risk_score, indicators, decision, infected_backup_id)
        """
        risk_score = 0
        indicators = []
        node_id = event.get('node_id')
        
        # Get the backup ID that contains this potentially infected file
        # This is the backup where the file was last backed up (may be infected)
        infected_backup_id = event.get('backup_version_id', 'unknown')
        
        # 1. Check entropy (high entropy = likely encrypted)
        entropy = float(event.get('entropy', 0))
        if entropy > 7.8:
            risk_score += 4
            indicators.append('very_high_entropy')
        elif entropy > 7.0:
            risk_score += 2
            indicators.append('high_entropy')
            
        # 2. Check process name
        process_name = event.get('process_name', '').lower()
        if 'ransom' in process_name:
            risk_score += 3
            indicators.append('suspicious_process')
        elif 'unknown' in process_name:
            risk_score += 1
            indicators.append('unknown_process')
            
        # 3. Check file name patterns
        file_indicators = self.check_file_content_indicators(event.get('file_path', ''))
        indicators.extend(file_indicators)
        risk_score += len(file_indicators) * 2
        
        # 4. Check for rapid file changes (behavioral)
        recent = self.event_history.get(node_id, [])
        recent_modifications = [e for e in recent if e.get('event_type') == 'FILE_MODIFIED']
        if len(recent_modifications) > 10:
            risk_score += 2
            indicators.append('rapid_file_changes')
            
        # 5. Check off-hours activity
        try:
            timestamp = event.get('timestamp', '')
            hour = datetime.fromisoformat(timestamp.replace('Z', '+00:00')).hour
            if hour < 6 or hour > 22:
                risk_score += 1
                indicators.append('off_hours_activity')
        except:
            pass
            
        # Determine decision based on risk
        if risk_score >= 7 or any('ransom_pattern' in i for i in indicators):
            decision = "ISOLATE"  # High risk: isolate node
        elif risk_score >= 4:
            decision = "BACKUP"   # Medium risk: just backup (but we still send backup ID)
        else:
            decision = "SAFE"     # Low risk: no action needed
            
        return risk_score, indicators, decision, infected_backup_id

    def send_result_to_gateway(self, original_event, risk_score, indicators, decision, infected_backup_id):
        """
        Send analysis result back to Gateway.
        Includes the backup_id of the potentially infected file so Gateway/Recovery Manager
        can restore from the backup BEFORE this one.
        """
        result = {
            # Identification
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "detector_id": self.detector_id,
            "node_id": original_event.get("node_id"),
            "file_path": original_event.get("file_path"),
            
            # Analysis results
            "decision": decision,  # ISOLATE, BACKUP, or SAFE
            "risk_score": risk_score,
            "risk_level": "HIGH" if risk_score >= 7 else ("MEDIUM" if risk_score >= 4 else "LOW"),
            "indicators": ",".join(indicators) if indicators else "none",
            
            # CRITICAL: Backup ID of the potentially infected file
            # Recovery Manager should use the backup BEFORE this one
            "infected_backup_id": infected_backup_id,
            
            # Original event data for context
            "original_event": {
                "entropy": original_event.get("entropy"),
                "process_name": original_event.get("process_name"),
                "timestamp": original_event.get("timestamp"),
                "backup_version_id": original_event.get("backup_version_id")
            }
        }
        
        # Send to Gateway via Redis Stream
        try:
            self.redis_client.xadd(self.output_stream, result)
            self.processed_count += 1
            
            # Log based on severity
            if decision == "ISOLATE":
                self.logger.warning(f"🚨 ISOLATE: {original_event.get('file_path')} (Risk: {risk_score}, InfectedBackup: {infected_backup_id})")
            elif decision == "BACKUP":
                self.logger.info(f"⚠️  BACKUP: {original_event.get('file_path')} (Risk: {risk_score}, InfectedBackup: {infected_backup_id})")
            else:
                self.logger.info(f"✅ SAFE: {original_event.get('file_path')} (Risk: {risk_score})")
                
        except Exception as e:
            self.logger.error(f"Failed to send result to Gateway: {e}")

    def run(self):
        """Main loop: receive events from Gateway, analyze, send results back"""
        self.logger.info("Waiting for file events from Gateway...")
        
        while True:
            try:
                # Read events from Gateway (blocking wait)
                messages = self.redis_client.xread(
                    {self.input_stream: '0'},
                    count=1,
                    block=5000
                )
                
                if not messages:
                    continue
                    
                # Process the event
                _stream, msg_list = messages[0]
                msg_id, event_data = msg_list[0]
                
                # Delete from stream (we've claimed it)
                self.redis_client.xdel(self.input_stream, msg_id)
                
                # Log receipt
                self.logger.info(f"Received: {event_data.get('file_path')} from node {event_data.get('node_id')}")
                
                # Analyze the file event
                risk_score, indicators, decision, infected_backup_id = self.analyze_event(event_data)
                
                # Send result back to Gateway (with infected backup ID)
                self.send_result_to_gateway(event_data, risk_score, indicators, decision, infected_backup_id)
                
                # Store in history for behavioural analysis
                node_id = event_data.get('node_id')
                if node_id not in self.event_history:
                    self.event_history[node_id] = []
                self.event_history[node_id].append(event_data)
                
                # Keep history manageable (last 100 events per node)
                if len(self.event_history[node_id]) > 100:
                    self.event_history[node_id].pop(0)
                    
            except KeyboardInterrupt:
                self.logger.info("Shutting down detector...")
                self._unregister()
                break
                
            except Exception as e:
                self.logger.error(f"Error processing event: {e}")
                time.sleep(1)

    def _unregister(self):
        """Unregister from Gateway on shutdown"""
        reg = {
            "event": "DETECTOR_UNREGISTERED",
            "detector_id": self.detector_id,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
        try:
            self.redis_client.xadd("detector_registrations", reg)
        except:
            pass


if __name__ == "__main__":
    import sys
    detector_id = sys.argv[1] if len(sys.argv) > 1 else None
    detector = RansomwareDetector(detector_id=detector_id)
    detector.run()