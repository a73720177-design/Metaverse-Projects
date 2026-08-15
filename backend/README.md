# Local AI Review Backend

FastAPI와 Ollama를 이용해 로컬 문서를 분석하고 평가자 페르소나를 생성하는 백엔드 MVP입니다.

## 준비

1. Python 3.11 이상과 Ollama를 설치합니다. 이 프로젝트는 Python 3.14에서도 검증합니다.
2. Ollama 모델을 준비합니다.

```powershell
ollama pull qwen2.5:7b
```

3. 가상환경과 패키지를 설치합니다.

```powershell
cd backend
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## 실행

```powershell
uvicorn app.main:app --reload
```

- API 문서: http://localhost:8000/docs
- 상태 확인: http://localhost:8000/health

환경 변수로 Ollama 설정을 바꿀 수 있습니다.

```powershell
$env:OLLAMA_BASE_URL = "http://localhost:11434"
$env:OLLAMA_MODEL = "qwen2.5:7b"
```

## 주요 API

- `POST /agents`: 자연어 설명으로 평가자 페르소나 생성
- `POST /documents/parse`: PPTX, PDF, DOCX 업로드 및 텍스트 추출
- `POST /agents/{agent_id}/reviews`: 문서 리뷰 생성 요청
- `GET /reviews/{review_id}`: 리뷰 결과 조회
- `POST /agents/{agent_id}/chat`: 평가자 관점 대화 요청
- `GET /health`: 서버 상태 확인

## 팀 역할과 연동

백엔드는 HTTP API, 입력 검증, 파일 업로드, 오류 응답과 서비스 조합을 담당합니다.
LLM 모델·프롬프트 구현과 DB·Vector DB 구현은 각각 담당 팀원의 어댑터로 연결합니다.

- LLM 계약: `app/ports/persona_generator.py`
- DB 계약: `app/ports/agent_repository.py`
- 구현 연결: `app/dependencies.py`
- 상세 계약: `docs/INTEGRATION_CONTRACTS.md`

현재 `InMemoryAgentRepository`는 DB 구현 전 개발용이며 서버 재시작 시 데이터가 사라집니다.
`OllamaPersonaGenerator`는 LLM 담당자가 교체하거나 확장할 수 있는 참고 구현입니다.

## 테스트

```powershell
pytest
```
