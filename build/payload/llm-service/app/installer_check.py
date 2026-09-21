"""Installer-only probes with progress and actionable failures; no user data."""

import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request


def probe(label, endpoint, payload, validate, *, base_url=None, headers=None):
    done = threading.Event()
    started = time.monotonic()

    def progress():
        while not done.wait(30):
            print(
                f"{label}: waiting {int(time.monotonic() - started)}s "
                "(CPU model loading may be slow)",
                flush=True,
            )

    print(f"Checking {label}...", flush=True)
    worker = threading.Thread(target=progress, daemon=True)
    worker.start()
    try:
        request = urllib.request.Request(
            f"{(base_url or os.getenv('OLLAMA_HOST', 'http://ollama:11434') + '/api').rstrip('/')}/{endpoint}",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", **(headers or {})},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=1800) as response:
            data = json.load(response)
        if data.get("error") or not validate(data):
            raise RuntimeError(
                f"{label}: invalid/empty result: {data.get('error', 'empty output')}"
            )
        print(f"{label}: passed", flush=True)
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read(1500).decode(errors="replace")
        finally:
            exc.close()
        raise RuntimeError(
            f"{label}: HTTP {exc.code}: {detail}. "
            "Check model server logs and Docker memory/disk allocation."
        ) from exc
    except (TimeoutError, urllib.error.URLError) as exc:
        raise RuntimeError(
            f"{label}: connection failure or 30-minute timeout ({exc}). Check Docker "
            "resources and Ollama logs, then rerun the EXE. Windows restart is not "
            "required by this test."
        ) from exc
    finally:
        done.set()
        worker.join(timeout=1)


def main():
    chat_model = os.getenv("OLLAMA_CHAT_MODEL", "qwen3:4b").strip()
    if chat_model not in {"qwen3:4b", "qwen3.5:9b"}:
        raise RuntimeError(f"Unsupported installer chat model: {chat_model}")
    provider = os.getenv("LLM_PROVIDER", "ollama").strip().lower()
    if provider not in {"ollama", "vllm"}:
        raise RuntimeError(f"Unsupported generation provider: {provider}")
    if provider == "vllm":
        model = os.getenv("VLLM_MODEL", "").strip()
        if not model:
            raise RuntimeError("VLLM_MODEL is required for the vLLM probe")
        api_key = os.getenv("VLLM_API_KEY", "").strip()
        probe(
            f"vLLM {model} generation", "chat/completions",
            {"model": model, "messages": [{"role": "user", "content": "Reply with OK."}],
             "max_tokens": 32, "stream": False,
             "chat_template_kwargs": {"enable_thinking": False}},
            lambda data: bool(data.get("choices") and isinstance(
                data["choices"][0].get("message", {}).get("content"), str)
                and data["choices"][0]["message"]["content"].strip()),
            base_url=os.getenv("VLLM_BASE_URL", "http://vllm:8000").rstrip('/') + '/v1',
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
        )
    else:
        probe(
            f"{chat_model} generation",
            "generate",
            {
                "model": chat_model,
                "prompt": "Reply with OK.",
                "stream": False,
                "think": False,
                "keep_alive": 0,
                "options": {"num_predict": 16, "num_ctx": 4096},
            },
            lambda data: bool(data.get("response", "").strip()),
        )
    probe(
        "bge-m3 embeddings",
        "embed",
        {"model": "bge-m3", "input": "Installer health check", "keep_alive": 0},
        lambda data: bool(data.get("embeddings") and data["embeddings"][0]),
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"AI CHECK FAILED: {exc}", file=sys.stderr, flush=True)
        sys.exit(1)
