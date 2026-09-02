from __future__ import annotations

import argparse
import os
import shlex
import subprocess

from dotenv import load_dotenv


def build_command() -> list[str]:
    load_dotenv()
    model = os.getenv("VLLM_MODEL", "").strip()
    if not model:
        raise ValueError("VLLM_MODEL is required.")

    command = [
        "vllm",
        "serve",
        model,
        "--host",
        os.getenv("VLLM_HOST", "127.0.0.1"),
        "--port",
        os.getenv("VLLM_PORT", "8002"),
        "--generation-config",
        "vllm",
        "--max-model-len",
        os.getenv("VLLM_MAX_MODEL_LEN", "8192"),
        "--gpu-memory-utilization",
        os.getenv("VLLM_GPU_MEMORY_UTILIZATION", "0.90"),
        "--max-num-seqs",
        os.getenv("VLLM_MAX_NUM_SEQS", "4"),
        "--kv-cache-dtype",
        os.getenv("VLLM_KV_CACHE_DTYPE", "auto"),
    ]
    quantization = os.getenv("VLLM_QUANTIZATION", "").strip()
    if quantization:
        command.extend(["--quantization", quantization])
    api_key = os.getenv("VLLM_API_KEY", "").strip()
    if api_key:
        command.extend(["--api-key", api_key])
    return command


def main() -> int:
    parser = argparse.ArgumentParser(description="Start the configured local vLLM server.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        command = build_command()
    except ValueError as exc:
        parser.error(str(exc))
    if args.dry_run:
        redacted = ["***" if command[index - 1] == "--api-key" else value for index, value in enumerate(command)]
        print(shlex.join(redacted))
        return 0
    return subprocess.call(command)


if __name__ == "__main__":
    raise SystemExit(main())
