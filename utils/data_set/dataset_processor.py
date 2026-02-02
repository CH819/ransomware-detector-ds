import csv
import json
import os
from datetime import datetime

READ_CSV = "utils/data_set/ata_read.csv"
WRITE_CSV = "utils/data_set/ata_write.csv"
OUTPUT_JSON = "utils/data_set/ransap_features.json"
OUTPUT_CSV = "utils/data_set/ransap_training.csv"

WINDOW_SIZE = 10


def parse_timestamp(sec, ns):
    return int(sec) + int(ns) / 1e9


def scale_entropy(entropy_val):
    """Scale 0.0-1.0 to 1-10."""
    clamped = max(0.0, min(1.0, float(entropy_val)))
    return round(1 + (clamped * 9), 1)


def calculate_velocity(operations, window_size):
    """Calculate speed/burstiness."""
    if len(operations) < 2:
        return {
            'ops_per_second': 0.0,
            'bytes_per_second': 0.0,
            'burst_score': 0
        }
    
    ops_per_sec = len(operations) / window_size
    total_bytes = sum(op['size'] for op in operations)
    bytes_per_sec = total_bytes / window_size
    
    # Burst detection
    timestamps = sorted([op['timestamp'] for op in operations])
    gaps = [timestamps[i+1] - timestamps[i] for i in range(len(timestamps)-1)]
    
    if gaps:
        avg_gap = sum(gaps) / len(gaps)
        if avg_gap > 0:
            variance = sum((g - avg_gap) ** 2 for g in gaps) / len(gaps)
            burst_score = min(10, int(variance / avg_gap * 10))
        else:
            burst_score = 10
    else:
        burst_score = 0
    
    return {
        'ops_per_second': round(ops_per_sec, 2),
        'bytes_per_second': round(bytes_per_sec, 0),
        'burst_score': burst_score
    }


def extract_windows(filepath, is_ransomware, has_entropy):
    operations = []
    
    try:
        with open(filepath, 'r') as f:
            reader = csv.reader(f)
            next(reader)
            for row in reader:
                if len(row) >= 4:
                    op = {
                        'timestamp': parse_timestamp(row[0], row[1]),
                        'size': int(row[3])
                    }
                    if has_entropy and len(row) >= 5:
                        op['entropy'] = float(row[4])
                    operations.append(op)
    except FileNotFoundError:
        return []
    
    if not operations:
        return []
    
    operations.sort(key=lambda x: x['timestamp'])
    min_time = operations[0]['timestamp']
    max_time = operations[-1]['timestamp']
    
    features = []
    window_start = min_time
    
    while window_start + WINDOW_SIZE <= max_time:
        window_end = window_start + WINDOW_SIZE
        window_ops = [op for op in operations if window_start <= op['timestamp'] < window_end]
        
        if not window_ops:
            window_start += 1
            continue
        
        # Entropy (1-10)
        if has_entropy:
            entropies = [scale_entropy(op['entropy']) for op in window_ops]
            avg_entropy = round(sum(entropies) / len(entropies), 1)
            max_entropy = max(entropies)
        else:
            avg_entropy = 2.0
            max_entropy = 2.0
        
        # Speed
        velocity = calculate_velocity(window_ops, WINDOW_SIZE)
        
        feature = {
            'window_start': datetime.fromtimestamp(window_start).isoformat(),
            'avg_entropy_1_10': avg_entropy,
            'max_entropy_1_10': max_entropy,
            'ops_per_second': velocity['ops_per_second'],
            'bytes_per_second': int(velocity['bytes_per_second']),
            'burst_score': velocity['burst_score'],
            'operation_count': len(window_ops),
            'total_bytes': sum(op['size'] for op in window_ops),
            'is_ransomware': 1 if is_ransomware else 0,
        }
        
        features.append(feature)
        window_start += 1
    
    return features


def main():
    print("RanSAP Processor (Entropy + Speed only)")
    print("=" * 40)
    
    print("\nProcessing read.csv (NORMAL)...")
    normal = extract_windows(READ_CSV, is_ransomware=False, has_entropy=False)
    print(f"  Normal windows: {len(normal)}")
    
    print("\nProcessing write.csv (RANSOMWARE)...")
    ransomware = extract_windows(WRITE_CSV, is_ransomware=True, has_entropy=True)
    print(f"  Ransomware windows: {len(ransomware)}")
    
    all_features = normal + ransomware
    
    with open(OUTPUT_JSON, 'w') as f:
        json.dump(all_features, f, indent=2)
    
    with open(OUTPUT_CSV, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=all_features[0].keys())
        writer.writeheader()
        writer.writerows(all_features)
    
    print(f"\nTotal: {len(all_features)}")
    print(f"  Normal: {len(normal)}")
    print(f"  Ransomware: {len(ransomware)}")
    
    print("\nNormal sample:")
    for f in normal[:1]:
        print(f"  Entropy: {f['avg_entropy_1_10']}, Speed: {f['ops_per_second']}/s, Burst: {f['burst_score']}")
    
    print("\nRansomware sample:")
    for f in ransomware[:1]:
        print(f"  Entropy: {f['avg_entropy_1_10']}, Speed: {f['ops_per_second']}/s, Burst: {f['burst_score']}")


if __name__ == "__main__":
    main()