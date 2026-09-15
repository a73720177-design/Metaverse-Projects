"""Private subprocess entry point. Never print parser exceptions or source text on failure."""
import json
import os
import sys
from app.integrations.vision import VisionUnavailableError


def main():
    try:
        if os.name == "posix":
            import resource
            budget = int(os.getenv("PARSER_MEMORY_MB", "1024")) * 1024 * 1024
            if sys.platform.startswith("linux"):
                resource.setrlimit(resource.RLIMIT_AS, (budget, budget))
            else:
                # macOS rejects finite RLIMIT_DATA on current Python. Monitor
                # resident peak instead; this is a sampled limit, not a hard cap.
                import threading
                def monitor():
                    wait = threading.Event()
                    while not wait.wait(0.1):
                        if resource.getrusage(resource.RUSAGE_SELF).ru_maxrss > budget:
                            os._exit(70)
                threading.Thread(target=monitor, daemon=True).start()
        from pathlib import Path
        from app.services.document_service import parse_document
        document = parse_document(Path(sys.argv[1]), sys.argv[2])
        if len(document.sections) > 1000 or len(document.full_text) > 2_000_000:
            print(json.dumps({"error": "문서 분석 한도(1,000개 구간·200만 자)를 초과했습니다."}))
            return
        print(document.model_dump_json())
    except VisionUnavailableError:
        print(json.dumps({"error": "시각 분석 모델을 사용할 수 없습니다. 잠시 후 다시 시도해주세요.", "code": "vision_unavailable"}))
    except Exception:
        print(json.dumps({"error": "문서를 분석하지 못했습니다. 파일 형식과 분석 자원 제한을 확인해주세요."}))


if __name__ == "__main__":
    main()
