"""터미널에서 Ollama 채팅 모델을 선택하고 .env에 저장합니다."""

from pathlib import Path


DEFAULT_MODEL = "qwen3:4b"
MODELS = {
    "1": "qwen3:4b",
    "2": "qwen3.5:9b",
    "qwen3:4b": "qwen3:4b",
    "qwen3.5:9b": "qwen3.5:9b",
}


def choose_model() -> str:
    print("\n사용할 LLM 모델을 선택하세요.")
    print("  [1] qwen3:4b    - 빠른 실행, 낮은 메모리 사용 (권장)")
    print("  [2] qwen3.5:9b  - 더 높은 품질, 더 긴 다운로드와 높은 메모리 사용")
    while True:
        choice = input("선택 [1/2, 기본값 1]: ").strip()
        if not choice:
            return DEFAULT_MODEL
        if choice in MODELS:
            return MODELS[choice]
        print("1 또는 2를 입력하세요.")


def save_to_env(env_path: Path, model: str) -> None:
    """기존 설정은 보존하면서 OLLAMA_CHAT_MODEL만 갱신합니다."""
    key = "OLLAMA_CHAT_MODEL"
    new_line = f"{key}={model}"
    lines = (
        env_path.read_text(encoding="utf-8-sig").splitlines()
        if env_path.exists()
        else []
    )

    updated_lines: list[str] = []
    replaced = False
    for line in lines:
        if line.lstrip().startswith(f"{key}="):
            if not replaced:
                updated_lines.append(new_line)
                replaced = True
            continue
        updated_lines.append(line)

    if not replaced:
        updated_lines.append(new_line)

    env_path.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")


def main() -> None:
    OLLAMA_CHAT_MODEL = choose_model()
    env_path = Path(__file__).resolve().parent / ".env"
    save_to_env(env_path, OLLAMA_CHAT_MODEL)
    print(f"선택된 모델: {OLLAMA_CHAT_MODEL}")
    print(f"저장 완료: {env_path}")


if __name__ == "__main__":
    main()
