import argparse
from pathlib import Path


FIELDS_TO_KEEP = [
    "clients_requested",
    "active_clients",
    "infected_targets",
    "infect_percent",
    "detections_observed",
    "detection_rate_pct",
    "avg_latency_ms",
    "p95_latency_ms",
    "token",
]


def parse_runs(lines: list[str]) -> list[dict[str, str]]:
    runs: list[dict[str, str]] = []
    current: dict[str, str] | None = None

    for raw_line in lines:
        line = raw_line.rstrip("\n")

        if line.startswith("# Benchmark Run:"):
            if current is not None:
                runs.append(current)
            current = {"run_header": line}
            continue

        if current is None:
            continue

        if line.startswith("==="):
            continue

        if ":" not in line:
            continue

        if line.startswith(" ") or line.startswith("-"):
            continue

        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()

        if key in FIELDS_TO_KEEP:
            current[key] = value

    if current is not None:
        runs.append(current)

    return runs


def render_runs(runs: list[dict[str, str]]) -> str:
    blocks: list[str] = []
    for run in runs:
        block_lines = [run.get("run_header", "# Benchmark Run: unknown"), "=== BENCHMARK RESULT SUMMARY ==="]
        for field in FIELDS_TO_KEEP:
            block_lines.append(f"{field:<22}: {run.get(field, 'N/A')}")
        blocks.append("\n".join(block_lines))
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract concise benchmark results from benchmark_detection.log"
    )
    parser.add_argument(
        "--input",
        default="benchmark_detection.log",
        help="Path to source benchmark log (default: benchmark_detection.log)",
    )
    parser.add_argument(
        "--output",
        default="benchmark_results_only.log",
        help="Path to output summary log (default: benchmark_results_only.log)",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    if not input_path.exists():
        raise FileNotFoundError(f"Input log not found: {input_path}")

    lines = input_path.read_text(encoding="utf-8", errors="replace").splitlines()
    runs = parse_runs(lines)
    output_text = render_runs(runs)

    output_path.parent.mkdir(parents=True, exist_ok=True) if output_path.parent != Path("") else None
    output_path.write_text(output_text, encoding="utf-8")

    print(f"Input file : {input_path}")
    print(f"Output file: {output_path}")
    print(f"Runs written: {len(runs)}")


if __name__ == "__main__":
    main()
