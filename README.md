# React Sidebar App

간단한 Vite + React 예제입니다.

설치 및 실행:

```bash
npm install
npm run dev
```

기능:
- 좌측 사이드바 접기/펼치기
- 입력 필드는 처음에 공란으로 시작
- 추가 버튼으로 항목을 목록에 추가
- 우측 상단 페르소나 선택은 `localStorage`에 저장된 현재 페르소나를 기본값으로 사용

## 백엔드(LLM/DB) 연동

`src/api.js`가 백엔드와 통신하는 유일한 곳입니다. `.env`의 `VITE_API_BASE_URL`을
실제 백엔드 주소로 바꾸고, `streamChat()`의 엔드포인트 경로와 스트림 파싱 방식을
실제 백엔드 스펙에 맞게 수정하면 됩니다. 지금은 다음을 가정한 예시 구현입니다:

- `POST {VITE_API_BASE_URL}/api/chat/stream`, 요청 바디 `{ message, persona }`
- SSE 형식 응답: `data: {"delta": "..."}` 줄이 이어지다가 `data: [DONE]`로 종료

채팅 기록은 지금처럼 `localStorage`에 저장되고, 메시지 전송 시 LLM 응답만
백엔드에서 스트리밍으로 받아와 채팅 기록의 `reply` 필드에 저장합니다.
