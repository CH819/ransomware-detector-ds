import argparse
import json
import statistics
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path

TIME_FORMAT = "%Y-%m-%d %H:%M:%S,%f"


def parse_ts(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, TIME_FORMAT)
    except Exception:
        return None


def analyze_recovery_times(log_path: Path) -> list[dict]:
    starts_by_node: dict[str, deque[datetime]] = defaultdict(deque)
    pairs: list[dict] = []

    for raw_line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line:
            continue

        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        node_id = event.get("node_id")
        reason = event.get("reason")
        ts_raw = event.get("asctime")
        ts = parse_ts(ts_raw) if isinstance(ts_raw, str) else None

        if not node_id or ts is None:
            continue

        if reason == "recovery_started":
            starts_by_node[node_id].append(ts)
            continue

        if reason == "recovery_complete" and starts_by_node[node_id]:
            start_ts = starts_by_node[node_id].popleft()
            duration_s = (ts - start_ts).total_seconds()
            if duration_s >= 0:
                pairs.append(
                    {
                        "node_id": node_id,
                        "start": start_ts,
                        "end": ts,
                        "duration_seconds": duration_s,
                    }
                )

    return pairs


def summarize(pairs: list[dict]) -> str:
    if not pairs:
        return "No completed recovery cycles found (recovery_started -> recovery_complete)."

    durations = sorted(p["duration_seconds"] for p in pairs)
    avg_s = sum(durations) / len(durations)
    p50_s = statistics.median(durations)
    p95_index = max(0, int(0.95 * len(durations)) - 1)
    p95_s = durations[p95_index]
    max_s = durations[-1]
    min_s = durations[0]

    lines = [
        "=== RECOVERY TIME SUMMARY ===",
        f"completed_recoveries : {len(durations)}",
        f"avg_seconds          : {avg_s:.3f}",
        f"p50_seconds          : {p50_s:.3f}",
        f"p95_seconds          : {p95_s:.3f}",
        f"min_seconds          : {min_s:.3f}",
        f"max_seconds          : {max_s:.3f}",
        "",
        "=== LAST 5 RECOVERIES ===",
    ]

    for item in pairs[-5:]:
        lines.append(
            f"node={item['node_id']} start={item['start'].isoformat(timespec='seconds')} "
            f"end={item['end'].isoformat(timespec='seconds')} duration_s={item['duration_seconds']:.3f}"
        )

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze node recovery times from gateway log")
    parser.add_argument(
        "--log-file",
        default="logs/gateway.log",
        help="Path to gateway log file (default: logs/gateway.log)",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Optional output file for summary report",
    )
    args = parser.parse_args()

    log_file = Path(args.log_file)
    if not log_file.exists():
        raise FileNotFoundError(f"Log file not found: {log_file}")

    pairs = analyze_recovery_times(log_file)
    report = summarize(pairs)
    print(report)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True) if output_path.parent != Path("") else None
        output_path.write_text(report + "\n", encoding="utf-8")
        print(f"\nSaved report: {output_path}")


if __name__ == "__main__":
    main()
