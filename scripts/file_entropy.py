import argparse
import math
from collections import Counter
from pathlib import Path

CHUNK_SIZE = 65536  # 64 KB


def calculate_entropy(file_path: Path) -> float:
    counts = Counter()
    total_size = 0

    with file_path.open("rb") as file_obj:
        while True:
            chunk = file_obj.read(CHUNK_SIZE)
            if not chunk:
                break
            counts.update(chunk)
            total_size += len(chunk)

    if total_size == 0:
        return 0.0

    entropy = 0.0
    for count in counts.values():
        probability = count / total_size
        entropy -= probability * math.log2(probability)

    return round(entropy, 4)


def main():
    parser = argparse.ArgumentParser(description="Calculate Shannon entropy of a file.")
    parser.add_argument("file_path", help="Path to the file")
    args = parser.parse_args()

    target = Path(args.file_path)

    if not target.exists():
        raise SystemExit(f"Error: file not found: {target}")
    if not target.is_file():
        raise SystemExit(f"Error: not a file: {target}")

    entropy = calculate_entropy(target)
    print(entropy)


if __name__ == "__main__":
    main()
