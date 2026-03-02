import argparse
import math
import os
import re
import subprocess
import time
from datetime import datetime
from dataclasses import dataclass
from typing import Dict, List


CLIENT_PREFIX = "ransomware-detector-ds-client-"


@dataclass
class ClientNode:
    container: str
    node_id: str


@dataclass
class ScenarioResult:
    clients_requested: int
    active_clients: int
    client_node_ids: List[str]
    infected_targets: int
    infect_percent: float
    infected_target_node_ids: List[str]
    infected_files_by_node: Dict[str, List[str]]
    per_infected_detection: Dict[str, Dict[str, int | str | None]]
    detector_distribution: Dict[str, int]
    unique_detectors_used: int
    detections_observed: int
    detection_rate_pct: float
    avg_detection_latency_ms: float | None
    p95_detection_latency_ms: int | None
    token: str


def run_command(command: List[str], check: bool = True) -> str:
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if check and result.returncode != 0:
        raise RuntimeError(
            f"Command failed ({result.returncode}): {' '.join(command)}\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    return result.stdout.strip()


def docker_compose(*args: str) -> str:
    return run_command(["docker", "compose", *args])


def get_client_containers() -> List[str]:
    output = run_command(["docker", "ps", "--format", "{{.Names}}"])
    return [line.strip() for line in output.splitlines() if line.strip().startswith(CLIENT_PREFIX)]


def get_node_id(container_name: str) -> str:
    result = subprocess.run(
        ["docker", "logs", "--tail", "200", container_name],
        capture_output=True,
        text=True,
        check=False,
    )
    output = (result.stdout or "") + "\n" + (result.stderr or "")
    matches = re.findall(r'"node_id"\s*:\s*"([a-f0-9\-]+)"', output)
    if not matches:
        raise RuntimeError(f"Could not determine runtime node_id from logs: {container_name}")
    return matches[-1]


def get_client_map() -> List[ClientNode]:
    clients = []
    for container in get_client_containers():
        try:
            node_id = get_node_id(container)
            if node_id:
                clients.append(ClientNode(container=container, node_id=node_id))
        except RuntimeError:
            continue
    return clients


def parse_redis_stream_raw(raw: str) -> List[Dict[str, str]]:
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    messages: List[Dict[str, str]] = []

    index = 0
    while index < len(lines):
        line = lines[index]
        if "-" in line and line.split("-")[0].isdigit():
            message_id = line
            index += 1
            fields: Dict[str, str] = {"_id": message_id}
            while index + 1 < len(lines):
                key = lines[index]
                if "-" in key and key.split("-")[0].isdigit():
                    break
                value = lines[index + 1]
                fields[key] = value
                index += 2
            messages.append(fields)
            continue
        index += 1

    return messages


def inject_ransom_note(container_name: str, node_id: str, token: str) -> str:
    remote_dir = f"/nodes/{node_id}/documents"
    remote_path = f"{remote_dir}/{token}.README_TO_DECRYPT.txt"
    run_command(
        [
            "docker",
            "exec",
            container_name,
            "sh",
            "-lc",
            f"mkdir -p {remote_dir}; echo {token} > {remote_path}",
        ]
    )
    return remote_path


def read_detector_out(count: int) -> List[Dict[str, str]]:
    raw = docker_compose("exec", "redis", "redis-cli", "--raw", "XREVRANGE", "detector_out", "+", "-", "COUNT", str(count))
    return parse_redis_stream_raw(raw)


def run_benchmark(clients_requested: int, infect_percent: float, timeout_seconds: int, sample_limit: int) -> ScenarioResult:
    docker_compose("up", "-d", "--scale", f"client={clients_requested}", "client")
    time.sleep(8)

    client_map = get_client_map()
    if not client_map:
        raise RuntimeError("No active clients found for benchmark")

    infected_count = max(1, math.ceil(len(client_map) * (infect_percent / 100.0)))
    infected_count = min(infected_count, len(client_map))
    targets = client_map[:infected_count]
    client_node_ids = [client.node_id for client in client_map]
    infected_target_node_ids = [target.node_id for target in targets]
    infected_files_by_node: Dict[str, List[str]] = {client.node_id: [] for client in client_map}

    token = f"bench_{int(time.time() * 1000)}"
    attack_start_ms = int(time.time() * 1000)

    for target in targets:
        infected_path = inject_ransom_note(target.container, target.node_id, token)
        infected_files_by_node[target.node_id].append(infected_path)

    deadline = time.time() + timeout_seconds
    matching_events: List[Dict[str, str]] = []

    while time.time() < deadline:
        events = read_detector_out(sample_limit)
        matching_events = [
            event for event in events
            if token in event.get("file_path", "")
        ]

        unique_nodes = {event.get("node_id", "") for event in matching_events if event.get("node_id")}
        if len(unique_nodes) >= infected_count:
            break
        time.sleep(0.7)

    earliest_event_by_node: Dict[str, Dict[str, int | str | None]] = {}
    for event in matching_events:
        node_id = event.get("node_id", "")
        if not node_id or node_id not in infected_target_node_ids:
            continue
        msg_id = event.get("_id", "")
        if "-" not in msg_id:
            continue
        event_ms = int(msg_id.split("-")[0])
        detector_id = event.get("detector_id")
        current = earliest_event_by_node.get(node_id)
        if current is None or event_ms < int(current["event_ms"]):
            earliest_event_by_node[node_id] = {
                "event_ms": event_ms,
                "detector_id": detector_id,
            }

    latencies = []
    per_infected_detection: Dict[str, Dict[str, int | str | None]] = {}
    for node_id in infected_target_node_ids:
        detected_event = earliest_event_by_node.get(node_id)
        if detected_event is None:
            per_infected_detection[node_id] = {
                "detection_timestamp_ms": None,
                "detection_timestamp_iso": None,
                "latency_ms": None,
                "detector_id": None,
                "status": "not_detected",
            }
            continue

        detected_ms = int(detected_event["event_ms"])
        detector_id = detected_event.get("detector_id")
        latency_ms = detected_ms - attack_start_ms
        latencies.append(latency_ms)
        per_infected_detection[node_id] = {
            "detection_timestamp_ms": detected_ms,
            "detection_timestamp_iso": datetime.fromtimestamp(detected_ms / 1000).isoformat(timespec="milliseconds"),
            "latency_ms": latency_ms,
            "detector_id": detector_id,
            "status": "detected",
        }

    latencies.sort()
    avg_latency = None
    p95_latency = None

    if latencies:
        avg_latency = round(sum(latencies) / len(latencies), 2)
        p95_index = max(0, math.ceil(len(latencies) * 0.95) - 1)
        p95_latency = latencies[p95_index]

    unique_detected_nodes = {node_id for node_id in infected_target_node_ids if node_id in earliest_event_by_node}
    detection_rate = round((len(unique_detected_nodes) * 100.0) / infected_count, 2)

    detector_distribution: Dict[str, int] = {}
    for node_id in infected_target_node_ids:
        details = per_infected_detection.get(node_id, {})
        detector_id = details.get("detector_id")
        status = details.get("status")
        if status != "detected" or not detector_id:
            continue
        detector_key = str(detector_id)
        detector_distribution[detector_key] = detector_distribution.get(detector_key, 0) + 1

    return ScenarioResult(
        clients_requested=clients_requested,
        active_clients=len(client_map),
        client_node_ids=client_node_ids,
        infected_targets=infected_count,
        infect_percent=infect_percent,
        infected_target_node_ids=infected_target_node_ids,
        infected_files_by_node=infected_files_by_node,
        per_infected_detection=per_infected_detection,
        detector_distribution=detector_distribution,
        unique_detectors_used=len(detector_distribution),
        detections_observed=len(unique_detected_nodes),
        detection_rate_pct=detection_rate,
        avg_detection_latency_ms=avg_latency,
        p95_detection_latency_ms=p95_latency,
        token=token,
    )


def format_result(result: ScenarioResult) -> str:
    lines = []
    lines.append("=== BENCHMARK RUN ===")
    lines.append(f"clients_requested      : {result.clients_requested}")
    lines.append(f"active_clients         : {result.active_clients}")
    lines.append("client_node_ids        :")
    for node_id in result.client_node_ids:
        lines.append(f"  - {node_id}")
    lines.append(f"infected_targets       : {result.infected_targets}")
    lines.append(f"infect_percent         : {result.infect_percent}")
    lines.append("infected_target_ids    :")
    for node_id in result.infected_target_node_ids:
        lines.append(f"  - {node_id}")
    lines.append("infected_files_by_node :")
    for node_id in result.client_node_ids:
        files = result.infected_files_by_node.get(node_id, [])
        if not files:
            lines.append(f"  - {node_id}: []")
            continue
        lines.append(f"  - {node_id}:")
        for file_path in files:
            lines.append(f"      * {file_path}")
    lines.append("per_infected_detection :")
    for node_id in result.infected_target_node_ids:
        details = result.per_infected_detection.get(node_id, {})
        status = details.get("status", "not_detected")
        detected_ms = details.get("detection_timestamp_ms")
        detected_iso = details.get("detection_timestamp_iso")
        latency_ms = details.get("latency_ms")
        detector_id = details.get("detector_id")
        lines.append(
            f"  - {node_id}: status={status}, detector_id={detector_id}, detection_timestamp_ms={detected_ms}, detection_timestamp_iso={detected_iso}, latency_ms={latency_ms}"
        )
    lines.append(f"unique_detectors_used   : {result.unique_detectors_used}")
    lines.append("detector_distribution   :")
    if result.detector_distribution:
        for detector_id, count in sorted(result.detector_distribution.items()):
            lines.append(f"  - {detector_id}: {count}")
    else:
        lines.append("  - none")
    lines.append(f"detections_observed    : {result.detections_observed}")
    lines.append(f"detection_rate_pct     : {result.detection_rate_pct}")
    lines.append(f"avg_latency_ms         : {result.avg_detection_latency_ms}")
    lines.append(f"p95_latency_ms         : {result.p95_detection_latency_ms}")
    lines.append(f"token                  : {result.token}")
    return "\n".join(lines)


def print_result(result: ScenarioResult) -> None:
    print()
    print(format_result(result))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark ransomware detection latency for a configurable client scale and infection rate."
    )
    parser.add_argument("--clients", type=int, default=10, help="Client replicas to run")
    parser.add_argument(
        "--infect-percent",
        type=float,
        default=50.0,
        help="Percentage of active clients to infect (0-100)",
    )
    parser.add_argument("--timeout", type=int, default=45, help="Seconds to wait for detections")
    parser.add_argument(
        "--sample-limit",
        "-sample-limit",
        type=int,
        default=800,
        help="How many detector_out messages to scan",
    )
    parser.add_argument(
        "--log-file",
        default="logs/benchmark_manual_test.log",
        help="Path to benchmark output log file (default: logs/benchmark_manual_test.log)",
    )
    parser.add_argument(
        "--also-log-file",
        default=None,
        help="Optional second log file path to append the same benchmark result",
    )
    args = parser.parse_args()

    if args.clients < 1:
        raise ValueError("--clients must be at least 1")
    if args.infect_percent <= 0 or args.infect_percent > 100:
        raise ValueError("--infect-percent must be > 0 and <= 100")

    result = run_benchmark(args.clients, args.infect_percent, args.timeout, args.sample_limit)
    print_result(result)

    log_dir = os.path.dirname(args.log_file)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    timestamp = datetime.now().isoformat(timespec="seconds")
    formatted_result = format_result(result)

    with open(args.log_file, "a", encoding="utf-8") as log_file:
        log_file.write(f"\n# Benchmark Run: {timestamp}\n")
        log_file.write(formatted_result)
        log_file.write("\n")

    print(f"\nSaved benchmark log: {args.log_file}")

    if args.also_log_file:
        extra_log_dir = os.path.dirname(args.also_log_file)
        if extra_log_dir:
            os.makedirs(extra_log_dir, exist_ok=True)

        with open(args.also_log_file, "a", encoding="utf-8") as extra_log:
            extra_log.write(f"\n# Benchmark Run: {timestamp}\n")
            extra_log.write(formatted_result)
            extra_log.write("\n")

        print(f"Saved extra benchmark log: {args.also_log_file}")


if __name__ == "__main__":
    main()
