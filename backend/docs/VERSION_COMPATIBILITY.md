# Version and ownership matrix

각 기능은 별도 프로세스와 가상환경을 사용하므로 Python 패키지 버전을 모두 같게
맞출 필요는 없습니다. 팀 사이에서 반드시 맞춰야 하는 것은 HTTP API v1 JSON 계약입니다.

## Backend (backend team)

- Python: 3.14.7
- FastAPI: 0.139.2
- Pydantic: 2.13.4
- Uvicorn: 0.51.0
- HTTPX: 0.28.1
- LLM contract: `/api/v1`, header `X-Backend-Contract-Version: 1`

백엔드는 Ollama 모델과 프롬프트를 소유하거나 직접 호출하지 않습니다.

## LLM service (LLM team action required)

현재 브랜치는 FastAPI 0.115.0, Pydantic 2.9.2, Uvicorn 0.30.6과
unversioned `/extract-concepts`, `/generate-questions`를 사용합니다.

Backend의 `LLM_CONTRACT_MODE=legacy_questions`는 이 두 API를 Persona·Review 흐름에 임시 연결합니다. 따라서 팀 코드를 먼저 합쳐 통합 테스트할 수 있지만 Chat은 지원되지 않고 정식 v1 계약도 완성된 상태가 아닙니다.

필수 변경:

1. `/api/v1/health`, `/api/v1/personas`, `/api/v1/reviews`, `/api/v1/chat` 구현
2. `docs/LLM_HTTP_CONTRACT.md` 요청/응답 스키마 준수
3. Python 3.14를 사용한다면 Pydantic 2.13.4 이상으로 변경
4. Ollama 테스트 버전과 모델(`qwen3:14b`)을 README에 기록
5. Ollama structured output(`format: json` 또는 JSON schema) 사용
6. reasoning 출력을 사용할 경우 `thinking` 필드를 별도로 처리하거나 `think: false` 사용

LLM 팀이 Python 3.11~3.13을 유지한다면 내부 패키지 버전은 백엔드와 달라도 됩니다.

## DB/OCR (DB team action required)

DB/OCR은 PyTorch, Transformers, Surya 등 네이티브 의존성이 있으므로 Python 3.11 또는
3.12의 별도 가상환경을 권장합니다. 백엔드의 Python 3.14에 맞출 필요가 없습니다.

현재 requirements.txt에는 실제 import인 `psycopg2`, `minio`, `python-pptx`, `torch`,
`transformers`, `surya`, `Pillow`가 빠져 있고 DB 코드에서 사용하지 않는 FastAPI,
Uvicorn, Pydantic이 들어 있습니다. 실제 실행 환경에서 검증한 버전으로 다시 생성해야 합니다.

DB 팀은 `AgentRepository`, `DocumentRepository`, `ReviewRepository` 계약을 구현하고,
DB 접속 정보와 MinIO 키를 환경 변수로만 제공해야 합니다.

## Compatibility rule

- 패키지 버전: 각 서비스가 독립적으로 관리
- 서비스 API: `/api/v1` 계약을 모든 팀이 동일하게 사용
- 계약 변경: 기존 v1을 깨지 않고 `/api/v2` 추가
- UUID와 enum 값: 문자열 철자까지 동일하게 유지
- 통합 전: backend contract tests와 LLM OpenAPI schema 비교
