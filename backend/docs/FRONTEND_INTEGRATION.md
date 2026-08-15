# React + Vite 연동 안내

Frontend는 Backend, LLM, DB 중 Backend HTTP API만 호출합니다. LLM과 DB 주소를 React 코드에 넣지 않습니다.

## 호환성 결론

현재 Backend는 React + Vite와 호환됩니다.

- JSON 요청·응답: 표준 `fetch` 또는 Axios 사용 가능
- 문서 업로드: 브라우저 `FormData` 사용 가능
- Vite 기본 개발 주소 `http://localhost:5173`: CORS 허용
- Vite preview 기본 주소 `http://localhost:4173`: CORS 허용
- Hamachi `25.x.x.x`의 5173·4173 포트: 개발용 CORS 허용
- Backend Swagger: `http://백엔드주소:8000/docs`

## 프론트 환경 변수

Vite는 브라우저 코드에 공개할 환경 변수 이름을 `VITE_`로 시작해야 합니다. 이 값은 빌드 결과에 포함되므로 비밀번호나 API 키를 넣으면 안 됩니다.

프론트 프로젝트에 커밋할 `.env.example`:

```env
VITE_API_BASE_URL=http://127.0.0.1:8000
```

각 개발자가 사용하는 `.env.development.local`:

```env
# Backend와 같은 PC에서 개발할 때
VITE_API_BASE_URL=http://127.0.0.1:8000

# Backend 담당자의 Hamachi 서버에 연결할 때는 위 줄 대신 사용
# VITE_API_BASE_URL=http://25.8.141.133:8000
```

환경 변수를 바꾼 후에는 Vite 개발 서버를 다시 실행해야 합니다.

## 공통 API 클라이언트 예시

`src/api/client.js`:

```javascript
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL;

if (!API_BASE_URL) {
  throw new Error("VITE_API_BASE_URL이 설정되지 않았습니다.");
}

export async function apiFetch(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, options);
  const data = await response.json().catch(() => null);

  if (!response.ok) {
    const message = data?.error?.message ?? `HTTP ${response.status}`;
    throw new Error(message);
  }

  return data;
}
```

사용 예시:

```javascript
import { apiFetch } from "./api/client";

const health = await apiFetch("/health");
```

## 문서 업로드 예시

`Content-Type`을 직접 지정하지 않습니다. 브라우저가 multipart boundary를 자동으로 추가해야 합니다.

```javascript
const formData = new FormData();
formData.append("file", selectedFile);

const document = await apiFetch("/documents/parse", {
  method: "POST",
  body: formData,
});
```

## Vite 서버를 Hamachi로 공유

프론트 담당자 PC에서 실행합니다.

```powershell
npm run dev -- --host 0.0.0.0
```

다른 팀원은 다음 주소로 접속합니다.

```text
http://프론트담당자-Hamachi-IP:5173
```

프론트 담당자 PC의 Windows 방화벽에서도 TCP 5173을 Hamachi 대역에 허용해야 합니다.

## React 개발 시 주의 사항

- 개발 모드의 `StrictMode`에서는 일부 Effect가 두 번 실행될 수 있습니다. Agent·Review 생성 같은 POST 요청을 단순한 `useEffect`에 넣지 말고 사용자 이벤트에서 호출합니다.
- Backend 오류는 `{"error": {"code": "...", "message": "..."}}` 형식으로 처리합니다.
- UUID는 문자열로 보관하고 임의로 숫자로 변환하지 않습니다.
- LLM 응답은 오래 걸릴 수 있으므로 요청 중 로딩 상태와 재시도 안내를 표시합니다.
- `VITE_*` 값에는 비밀 정보를 넣지 않습니다.
