import redis
import logging
import time
import os
import socket
from dotenv import load_dotenv
from pythonjsonlogger import jsonlogger


load_dotenv()

REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))

STREAM_DETECTOR_IN = "detector_in"
STREAM_DETECTOR_OUT = "detector_out"

CONSUMER_GROUP = "detectors_cg"

LOG_FILE = os.environ.get("LOG_FILE", "/logs/detector.log")



class RansomwareDetector:
    def __init__(self, detector_id=None, redis_host=REDIS_HOST, redis_port=REDIS_PORT):
        if detector_id:
            self.detector_id = detector_id
        else:
            hostname = socket.gethostname()
            self.detector_id = f"detector-{hostname}-{os.getpid()}"
        self.redis = redis.Redis(host=redis_host, port=redis_port, decode_responses=True)

        # Logger config
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)

        file_handler = logging.FileHandler(LOG_FILE)
        file_handler.setLevel(logging.INFO)

        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)

        formatter = jsonlogger.JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")

        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)

        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)

        self.logger.propagate = False
        # ---
        
        self._join_consumer_group()
        
        self.logger.info(f"Detector {self.detector_id} started in group {CONSUMER_GROUP}")

    def _join_consumer_group(self):
        """Create/join consumer group for horizontal scaling."""
        try:
            self.redis.xgroup_create(STREAM_DETECTOR_IN, CONSUMER_GROUP, id="0", mkstream=True)
            self.logger.info(f"Created consumer group {CONSUMER_GROUP}")
        except redis.ResponseError as e:
            if "already exists" in str(e):
                self.logger.info(f"Joined existing consumer group {CONSUMER_GROUP}")
            else:
                raise

    def analyze_file(self, event: dict) -> tuple:
        """Analyze file for ransomware indicators."""
        risk_score = 0
        indicators = []
        
        infected_backup_id = event.get('backup_version_id', 'unknown')
        file_path = event.get('file_path', '')

        # Entropy check
        entropy = float(event.get('entropy', 0))
        if entropy >= 7.0:
            risk_score += 7
            indicators.append("very_high_entropy")
        elif entropy > 6.0:
            risk_score += 4
            indicators.append('high_entropy')
            
        # Process check
        process_name = event.get('process_name', '').lower()
        if 'ransom' in process_name:
            risk_score += 3
            indicators.append('suspicious_process')
            
        # File pattern check
        file_lower = file_path.lower()
        ransom_patterns = ['readme_to_decrypt', 'how_to_decrypt', '_readme', '_decrypt', 
                          'ransom_note', 'recover_files']
        for pat in ransom_patterns:
            if pat in file_lower:
                indicators.append(f'ransom_pattern:{pat}')
                risk_score += 4
                
        # Extension check
        encrypted_exts = ['.locked', '.encrypted', '.crypt', '.crypted', '.enc', '.aes', '.bin']
        for ext in encrypted_exts:
            if file_lower.endswith(ext):
                indicators.append(f'encrypted_ext:{ext}')
                risk_score += 4
        
        # Decision
        if risk_score >= 7:
            decision = "ISOLATE"
        elif risk_score >= 4:
            decision = "BACKUP"
        else:
            decision = "SAFE"
            
        return decision, risk_score, indicators, infected_backup_id

    def send_result(self, event: dict, decision: str, risk_score: int, 
                   indicators: list, infected_backup_id: str):
        """Send analysis result to Gateway."""
        result = {
            "detector_id": self.detector_id,
            "node_id": event.get("node_id"),
            "file_path": event.get("file_path"),
            "timestamp": event.get("timestamp", int(time.time() * 1000)),
            "decision": decision,
            "risk_score": risk_score,
            "risk_level": "HIGH"
            if risk_score >= 7
            else ("MEDIUM" if risk_score >= 4 else "LOW"),
            "indicators": ",".join(indicators) if indicators else "none",
            "infected_backup_id": infected_backup_id,
        }
        
        self.redis.xadd(STREAM_DETECTOR_OUT, result)
        
        # Include detector_id in message, not format
        self.logger.info(f"[{self.detector_id}] {decision}: {event.get('file_path')} (risk: {risk_score}, backup: {infected_backup_id})")

    def run(self):
        """Main loop with consumer group for horizontal scaling."""
        self.logger.info(f"Detector {self.detector_id} waiting for events...")
        
        while True:
            try:
                # Read from consumer group (load balanced across detectors)
                messages = self.redis.xreadgroup(
                    CONSUMER_GROUP,
                    self.detector_id,  # Unique consumer name
                    {STREAM_DETECTOR_IN: ">"},
                    count=1,
                    block=5000
                )

                if not messages:
                    continue
                
                for stream_name, msg_list in messages:
                    for msg_id, event in msg_list:
                        
                        # Use info level so it actually shows
                        self.logger.info(f"[{self.detector_id}] Processing {msg_id[:8]}... {event.get('file_path')}")
                        
                        # Analyze
                        decision, risk_score, indicators, backup_id = self.analyze_file(event)
                        
                        # Send result
                        self.send_result(event, decision, risk_score, indicators, backup_id)
                        
                        # Acknowledge
                        self.redis.xack(STREAM_DETECTOR_IN, CONSUMER_GROUP, msg_id)
                        
            except KeyboardInterrupt:
                self.logger.info(f"Detector {self.detector_id} shutting down...")
                break
            except Exception as e:
                if isinstance(e, redis.ResponseError) and "NOGROUP" in str(e):
                    self.logger.warning(
                        f"[{self.detector_id}] Consumer group missing, recreating..."
                    )
                    self._join_consumer_group()
                    time.sleep(0.2)
                    continue
                self.logger.error(f"[{self.detector_id}] Error: {e}", exc_info=True)
                time.sleep(1)


if __name__ == "__main__":
    import sys

    detector_id = sys.argv[1] if len(sys.argv) > 1 else None
    detector = RansomwareDetector(detector_id=detector_id)
    detector.run()
