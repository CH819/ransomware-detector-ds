import argparse
import hashlib
import secrets
from pathlib import Path


def xor_with_keystream(data: bytes, seed: bytes) -> bytes:
    result = bytearray(len(data))
    offset = 0
    block_index = 0

    while offset < len(data):
        block = hashlib.sha256(seed + block_index.to_bytes(8, "big")).digest()
        take = min(len(block), len(data) - offset)
        for i in range(take):
            result[offset + i] = data[offset + i] ^ block[i]
        offset += take
        block_index += 1

    return bytes(result)


def make_high_entropy_bytes(raw: bytes) -> bytes:
    nonce = secrets.token_bytes(32)
    seed = hashlib.sha256(raw + nonce).digest()
    transformed = xor_with_keystream(raw, seed)
    return nonce + transformed


def convert_file(input_path: Path, keep_original: bool) -> Path:
    if not input_path.exists():
        raise SystemExit(f"Error: file not found: {input_path}")
    if not input_path.is_file():
        raise SystemExit(f"Error: not a file: {input_path}")

    output_path = input_path.with_suffix(".bin")
    raw = input_path.read_bytes()
    high_entropy = make_high_entropy_bytes(raw)

    output_path.write_bytes(high_entropy)

    if output_path != input_path and not keep_original:
        input_path.unlink(missing_ok=True)

    return output_path


def convert_directory(directory_path: Path, keep_original: bool) -> list[Path]:
    if not directory_path.exists():
        raise SystemExit(f"Error: path not found: {directory_path}")
    if not directory_path.is_dir():
        raise SystemExit(f"Error: not a directory: {directory_path}")

    converted: list[Path] = []
    for file_path in directory_path.rglob("*"):
        if not file_path.is_file():
            continue
        if file_path.suffix.lower() == ".bin":
            continue
        converted.append(convert_file(file_path, keep_original=keep_original))

    return converted


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert a file or all files in a directory to high-entropy .bin files."
    )
    parser.add_argument(
        "input_path",
        help="Path to input file or directory (example: notes.txt or documents)",
    )
    parser.add_argument(
        "--keep-original",
        action="store_true",
        help="Keep the original input file instead of deleting it",
    )
    args = parser.parse_args()

    input_path = Path(args.input_path)

    if not input_path.exists():
        raise SystemExit(f"Error: path not found: {input_path}")

    if input_path.is_file():
        result = convert_file(input_path, keep_original=args.keep_original)
        print(f"Created high-entropy file: {result}")
        return

    if input_path.is_dir():
        converted = convert_directory(input_path, keep_original=args.keep_original)
        print(f"Converted {len(converted)} file(s) in: {input_path}")
        for output_path in converted:
            print(output_path)
        return

    raise SystemExit(f"Error: unsupported path type: {input_path}")


if __name__ == "__main__":
    main()
