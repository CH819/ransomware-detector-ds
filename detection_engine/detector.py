import redis
import json
import logging
import time
from datetime import datetime

class RansomwareDetector:
    def __init__(self, redis_host='localhost', redis_port=6379):
        self.redis_client = redis.Redis(host=redis_host, port=redis_port, decode_responses=True)
        self.input_stream  = "file_events"
        self.output_stream = "ransomware_alerts"
        self.event_history = {}
        #clean printing
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - DETECTOR - %(levelname)s - %(message)s\n'
        )
        self.logger = logging.getLogger(__name__)

    def check_file_content_indicators(self, file_path):
        indicators = []
        file_lower = file_path.lower()
        for pat in ['readme_to_decrypt', 'how_to_decrypt', 'decrypt_instructions',
                    'ransom_note', 'recover_files', 'unlock_files',
                    '_readme', '_decrypt', '_recover', '_unlock']:
            if pat in file_lower:
                indicators.append(f'ransom_pattern_{pat}')
        for ext in ['.locked', '.encrypted', '.crypt', '.crypted', '.enc']:
            if file_lower.endswith(ext):
                indicators.append(f'encrypted_extension_{ext}')
        return indicators

    def analyze_event(self, event):
        risk_score, indicators = 0, []

        # 1. entropy
        entropy = float(event['entropy'])
        if entropy > 7.8:
            risk_score += 4; indicators.append('very_high_entropy')
        elif entropy > 7.0:
            risk_score += 2; indicators.append('high_entropy')

        # 2. process
        process_name = event['process_name'].lower()
        if 'ransom' in process_name:
            risk_score += 3; indicators.append('ransom_in_process')
        elif 'unknown' in process_name:
            risk_score += 1; indicators.append('unknown_process')

        # 3. file name / extension
        for ind in self.check_file_content_indicators(event['file_path']):
            risk_score += 2; indicators.append(ind)

        # 4. rapid changes
        node_id = event['node_id']
        recent = [e for e in self.event_history.get(node_id, []) if e['event_type'] == 'FILE_MODIFIED']
        if len(recent) > 10:
            risk_score += 2; indicators.append('rapid_file_changes')

        # 5. off-hours
        hour = datetime.fromisoformat(event['timestamp'].replace('Z', '+00:00')).hour
        if hour < 6 or hour > 22:
            risk_score += 1; indicators.append('off_hours')

        return risk_score, indicators

    def make_decision(self, event, risk_score, indicators):
        if risk_score >= 7 or any('ransom_pattern' in i for i in indicators):
            decision, conf = "RANSOMWARE_DETECTED", "HIGH"
        elif risk_score >= 4:
            decision, conf = "SUSPICIOUS_ACTIVITY", "MEDIUM"
        else:
            decision, conf = "CLEAN", "HIGH"

        return {
            'timestamp': datetime.utcnow().isoformat() + "Z",
            'node_id': event['node_id'],
            'file_path': event['file_path'],
            'decision': decision,
            'confidence': conf,
            'risk_score': risk_score,
            'indicators': ','.join(indicators),
            'entropy': event['entropy'],
            'process_name': event['process_name'],
            'recommended_action': ("ISOLATE_NODE_AND_INITIATE_RECOVERY" if decision == "RANSOMWARE_DETECTED" else
                                  ("MONITOR_CLOSELY_AND_CHECK_BACKUPS" if decision == "SUSPICIOUS_ACTIVITY" else
                                   "CONTINUE_NORMAL_OPERATIONS")),
            'backup_version_id': event['backup_version_id']
        }

    def run(self):
        self.logger.info("Detector started, waiting for events...\n")
        while True:
            try:
                messages = self.redis_client.xread({self.input_stream: '0'}, count=1, block=5000)
                if messages:
                    _stream, msg_list = messages[0]
                    msg_id, data = msg_list[0]
                    self.redis_client.xdel(self.input_stream, msg_id)

                    self.logger.info(f"Analyzing: {data['file_path']} | Entropy: {data['entropy']}\n")
                    risk_score, indicators = self.analyze_event(data)
                    alert_data = self.make_decision(data, risk_score, indicators)

                    if alert_data['decision'] != "CLEAN":
                        self.redis_client.xadd(self.output_stream, alert_data)
                        self.logger.info(f"🚨 ALERT: {alert_data['decision']} (Risk: {risk_score}/10)\n")
                    else:
                        self.logger.info(f"✅ CLEAN  (Risk: {risk_score}/10)\n")

                    # store for history
                    node = data['node_id']
                    self.event_history.setdefault(node, []).append(data)
                    if len(self.event_history[node]) > 100:
                        self.event_history[node].pop(0)

            except KeyboardInterrupt:
                self.logger.info("Shutting down detector...\n")
                break
            except Exception as e:
                self.logger.error(f"Error: {e}\n")
                time.sleep(1)


if __name__ == "__main__":
    RansomwareDetector().run()