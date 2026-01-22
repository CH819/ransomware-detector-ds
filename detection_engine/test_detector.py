import redis
import json
import time
from datetime import datetime, timezone, timedelta

def test_detector():
    "Test detector with placeholder events"
    
    # Connect to Redis
    r = redis.Redis(host='localhost', port=6379, decode_responses=True)

    base_time = datetime.now(timezone.utc)
    ts = lambda seconds_offset: (base_time + timedelta(seconds=seconds_offset)).isoformat().replace('+00:00', 'Z')
    
    # Test events with different risk levels
    test_events = [
            # 1. clean
        {
            "node_id": "VM-01",
            "timestamp": ts(0),
            "event_type": "FILE_MODIFIED",
            "file_path": "/home/user/documents/report.pdf",
            "file_extension": ".pdf",
            "file_size_bytes": 1024,
            "entropy": 5.0,
            "process_name": "notepad.exe",
            "process_id": 1234,
            "backup_version_id": "v_001"
        },
        # 2. high entropy
        {
            "node_id": "VM-01",
            "timestamp": ts(30),
            "event_type": "FILE_MODIFIED",
            "file_path": "/home/user/documents/encrypted.pdf",
            "file_extension": ".pdf",
            "file_size_bytes": 1_048_576,
            "entropy": 9.0,
            "process_name": "unknown_script.py",
            "process_id": 4502,
            "backup_version_id": "v_002"
        },
        # 3. ransom note
        {
            "node_id": "VM-01",
            "timestamp": ts(60),
            "event_type": "FILE_CREATED",
            "file_path": "/home/user/documents/report.pdf.README_TO_DECRYPT.txt",
            "file_extension": ".txt",
            "file_size_bytes": 1024,
            "entropy": 5.0,
            "process_name": "ransomware_sim.py",
            "process_id": 4503,
            "backup_version_id": "v_003"
        },
        # 4. pattern in name
        {
            "node_id": "VM-01",
            "timestamp": ts(90),
            "event_type": "FILE_CREATED",
            "file_path": "/home/user/documents/HOW_TO_DECRYPT_FILES.txt",
            "file_extension": ".txt",
            "file_size_bytes": 2048,
            "entropy": 4.2,
            "process_name": "notepad.exe",
            "process_id": 1234,
            "backup_version_id": "v_004"
        },
        # 5. encrypted extension
        {
            "node_id": "VM-01",
            "timestamp": ts(120),
            "event_type": "FILE_MODIFIED",
            "file_path": "/home/user/pictures/photo.jpg.locked",
            "file_extension": ".locked",
            "file_size_bytes": 3_145_728,
            "entropy": 7.95,
            "process_name": "encryptor.exe",
            "process_id": 5678,
            "backup_version_id": "v_005"
        }
    ]
    print("Testing detector with placeholder events...")
    print("=" * 50)
    
    # Send events one by one
    for i, event in enumerate(test_events):
        print(f"\nSending test event {i+1}: {event['file_path']}")
        print(f"Entropy: {event['entropy']}")
        print(f"Process: {event['process_name']}")
        
        # Send to Redis
        r.xadd("file_events", event)
        
        # Wait a bit between events
        time.sleep(2)
    
    print("\nAll test events sent!")
    print("Check detector logs to see analysis results...")

def check_redis_streams():
    "Check what's in Redis streams"
    r = redis.Redis(host='localhost', port=6379, decode_responses=True)
    
    print("\nRedis Streams Status:")
    print("-" * 30)
    
    # Check input stream
    try:
        input_info = r.xinfo_stream("file_events")
        print(f"file_events: {input_info['length']} messages")
    except:
        print("file_events: 0 messages")
    
    # Check output stream
    try:
        output_info = r.xinfo_stream("ransomware_alerts")
        print(f"ransomware_alerts: {output_info['length']} alerts")
        
        # Show recent alerts
        alerts = r.xrevrange("ransomware_alerts", count=5)
        print("\nRecent Alerts:")
        for msg_id, alert in alerts:
            print(f"   {alert['decision']} - {alert['file_path']} (Risk: {alert['risk_score']})")
            
    except:
        print("ransomware_alerts: 0 messages")

def clear_redis_streams():
    "Clear all Redis streams"
    r = redis.Redis(host='localhost', port=6379, decode_responses=True)
    r.delete("file_events")
    r.delete("ransomware_alerts")
    print("Redis streams cleared")

if __name__ == "__main__":
    # Clear existing data
    clear_redis_streams()
    
    # Test the detector
    test_detector()
    
    # Give detector time to process
    time.sleep(3)
    
    # Check results
    check_redis_streams()