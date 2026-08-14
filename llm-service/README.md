# LLM Service

발표 자료(논문)와 대본을 받아, 핵심 개념을 추출하고 비판 질문을 생성하는 API 서버입니다.
Ollama(qwen3:14b)를 로컬에서 호출합니다.

## 사전 준비

1. [Ollama](https://ollama.com/download) 설치
2. 모델 다운로드: `ollama pull qwen3:14b`
3. Ollama 서버 실행 확인 (기본적으로 설치 시 자동 실행됨, 안 되어 있으면 `ollama serve`)

## 실행 방법

```bash
# 1. 가상환경 생성 (최초 1회)
python -m venv .venv
.venv\Scripts\activate      # Windows
# source .venv/bin/activate  # Mac/Linux

# 2. 패키지 설치
pip install -r requirements.txt

# 3. 환경변수 설정 (최초 1회)
copy .env.example .env      # Windows
# cp .env.example .env       # Mac/Linux

# 4. 서버 실행
uvicorn app.main:app --reload --port 8001
```

서버가 뜨면 `http://localhost:8001/docs` 에서 Swagger UI로 API를 바로 테스트해볼 수 있습니다.

## API

### `GET /health`
서버 상태 확인용.

### `POST /extract-concepts`
논문 본문에서 핵심 개념 8개를 추출합니다.

요청 예시:
```json
{
  "paper_text": "여기에 논문 본문 전체 텍스트..."
}
```

응답 예시:
```json
{
  "concepts": [
    {"name": "의인화 매커니즘", "definition": "..."}
  ]
}
```

### `POST /generate-questions`
1단계 결과(concepts)와 발표 대본을 바탕으로 비판 질문 5개를 생성합니다.

요청 예시:
```json
{
  "concepts": [{"name": "...", "definition": "..."}],
  "critical_points": "사용자 중심의 기술 설계, 데이터의 편향성, 투명성과 공정성",
  "script_text": "여기에 발표 대본 전체 텍스트..."
}
```

응답 예시:
```json
{
  "questions": [
    {"question": "..."}
  ]
}
```

## 참고

- 프롬프트는 맥북(M4)과 Windows(RX 9060 XT) 양쪽에서 검증 완료된 버전입니다 (기획서 8-2절 참고).
- 백엔드 담당자는 이 API를 그대로 호출해서 사용하면 됩니다. 인터페이스(요청/응답 형식) 변경이
  필요하면 `app/schemas.py`를 먼저 협의 후 수정해주세요.
