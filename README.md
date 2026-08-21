# 발표 도우미 Frontend

React와 Vite로 구현한 발표자료 검토·채팅 화면입니다. 브라우저는 Backend만 호출하며 LLM, Ollama, PostgreSQL, MinIO에 직접 접근하지 않습니다.

## 실행

Node.js 22.12 이상이 필요합니다.

```powershell
npm.cmd ci
Copy-Item .env.example .env.local
npm.cmd run dev -- --host 0.0.0.0
```

- 개발 화면: <http://localhost:5173>
- Backend 기본 주소: <http://127.0.0.1:8000>

PowerShell 실행 정책으로 `npm.ps1`이 차단되면 정책을 변경하지 않고 `npm.cmd`를 사용합니다.

## 환경변수

```env
VITE_API_BASE_URL=http://127.0.0.1:8000
```

Hamachi에서는 Backend PC의 Hamachi IP를 사용합니다.

```env
VITE_API_BASE_URL=http://25.x.x.x:8000
```

`.env.local`은 Git에 커밋하지 않습니다.

## 현재 Backend 연동

| 기능 | Backend API |
|---|---|
| 페르소나 생성 | `POST /agents` |
| 문서 업로드·분석 | `POST /documents/parse` |
| 페르소나 채팅 | `POST /agents/{agent_id}/chat` |

페르소나를 만들 때 Backend가 발급한 `agent_id`를 저장합니다. 선택 문서가 있으면 `document_id`도 저장하여 채팅 요청에 전달합니다. API 오류는 Backend 공통 형식인 `{error: {code, message}}`를 우선 처리합니다.

현재 Backend에는 인증 API와 SSE 채팅 API가 없으므로 로그인 UI와 `/api/chat/stream` 가정은 제거했습니다. 채팅 기록은 화면에서 멀티턴으로 보관하지만 Backend에는 현재 질문 한 건과 선택적 `document_id`를 전송합니다.

화면 상단의 상태 카드는 Backend의 `GET /health/services`를 호출해 Frontend, Backend, DB, LLM 연결을 함께 표시합니다. 15초마다 자동으로 갱신되며 수동 새로고침도 지원합니다. 초록색은 연결됨, 노란색은 외부 PostgreSQL을 사용하지 않는 개발 모드, 빨간색은 연결 실패를 의미합니다.

자세한 요청·응답은 [Frontend API 계약](./FRONTEND_INTEGRATION.md)을 확인합니다.

## 파일 업로드

- 허용 형식: `.pptx`, `.pdf`, `.docx`
- 최대 크기: 25MB
- 현재 페르소나당 연결 문서: 1개
- `FormData`를 사용하며 `Content-Type` 헤더를 브라우저가 설정하게 둡니다.

## 브라우저 저장소

채팅 목록과 Backend에서 발급받은 `agent_id`, `document_id`를 `localStorage`에 저장합니다. 비밀번호와 인증 토큰은 저장하지 않습니다. Backend 데이터 삭제 API가 아직 없으므로 화면에서 페르소나를 삭제해도 Backend 레코드는 삭제되지 않습니다.

## 검사

```powershell
npm.cmd run build
npm.cmd audit --audit-level=moderate
```

2026-08-22 기준 Vite `8.2.2`로 build가 성공하며 npm 취약점은 0건입니다.

## 추가 작업

- 자동화된 컴포넌트·API 클라이언트 테스트 추가
- ESLint와 CI build 검사 추가
- Backend 삭제 API 확정 후 페르소나·문서 삭제 연동
- 모바일 화면에서 사이드바를 overlay 또는 drawer 방식으로 개선
- Backend가 대화 이력을 지원할 때 멀티턴 요청 계약 추가
