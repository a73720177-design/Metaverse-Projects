from __future__ import annotations

import argparse
import concurrent.futures
import json
import statistics
import time
from dataclasses import asdict, dataclass
from uuid import uuid4

import requests


@dataclass
class Result:
    ok: bool
    first_token_seconds: float | None
    total_seconds: float
    chunks: int
    characters: int
    error: str | None = None


def build_payload(message: str, max_output_tokens: int, document_chars: int) -> dict:
    payload = {
        "persona": {
            "agent_id": str(uuid4()),
            "name": "성능 측정 평가자",
            "description": "근거와 개선점을 명확하게 설명한다.",
            "role": "Evaluator",
            "expertise": [],
            "evaluation_style": [],
        },
        "message": message,
        "max_output_tokens": max_output_tokens,
        "document": None,
    }
    if document_chars:
        payload["document"] = {
            "document_id": str(uuid4()),
            "filename": "benchmark.txt",
            "document_type": "txt",
            "sections": [],
            "full_text": "발표 근거와 개선 사항을 검토합니다. " * (document_chars // 20 + 1),
        }
        payload["document"]["full_text"] = payload["document"]["full_text"][:document_chars]
    return payload


def run_once(url: str, payload: dict, timeout: float) -> Result:
    started = time.perf_counter()
    first_token: float | None = None
    chunks = 0
    characters = 0
    try:
        with requests.post(url, json=payload, stream=True, timeout=timeout) as response:
            response.raise_for_status()
            for line in response.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data:"):
                    continue
                data = json.loads(line.removeprefix("data:").strip())
                token = data.get("token", "")
                if token:
                    if first_token is None:
                        first_token = time.perf_counter() - started
                    chunks += 1
                    characters += len(token)
        return Result(True, first_token, time.perf_counter() - started, chunks, characters)
    except (requests.RequestException, ValueError) as exc:
        return Result(False, first_token, time.perf_counter() - started, chunks, characters, str(exc))


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark LLM chat SSE latency and concurrency.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--concurrency", type=int, default=1, choices=(1, 2, 4, 8))
    parser.add_argument("--requests", type=int, default=3)
    parser.add_argument("--max-output-tokens", type=int, default=1536, choices=(512, 1024, 1536))
    parser.add_argument("--document-chars", type=int, default=2000)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--message", default="이 발표의 핵심 문제와 개선안을 근거와 함께 설명해 주세요.")
    args = parser.parse_args()

    payload = build_payload(args.message, args.max_output_tokens, args.document_chars)
    url = f"{args.base_url.rstrip('/')}/api/v1/chat/stream"
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        results = list(
            executor.map(
                lambda _: run_once(url, payload, args.timeout),
                range(args.requests),
            )
        )

    successes = [result for result in results if result.ok]
    summary = {
        "configuration": vars(args),
        "success_rate": len(successes) / len(results),
        "first_token_seconds_p50": (
            statistics.median(result.first_token_seconds for result in successes if result.first_token_seconds is not None)
            if any(result.first_token_seconds is not None for result in successes)
            else None
        ),
        "total_seconds_p50": statistics.median(result.total_seconds for result in successes) if successes else None,
        "results": [asdict(result) for result in results],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if len(successes) == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
