# 채팅 소스 파일 첨부 흐름

Frontend 채팅 입력창은 PPTX, PDF, DOCX 파일의 선택 및 드래그앤드롭을 지원합니다.

1. `POST /documents/parse`에 원본 파일을 multipart/form-data로 업로드합니다.
2. Backend가 파일을 저장하고 텍스트를 추출해 `document_id`를 반환합니다.
3. Frontend가 `POST /agents/{agent_id}/chat` 요청의 `document_id`에 해당 값을 전달합니다.
4. Backend가 소유권을 확인한 뒤 추출된 전체 텍스트와 페르소나를 LLM 채팅 문맥으로 전달합니다.
5. 생성된 채팅 이력에도 `document_id`가 저장되어 어떤 자료를 사용했는지 추적할 수 있습니다.

지원 형식은 `.pptx`, `.pdf`, `.docx`이며 기본 최대 크기는 25MB입니다. 파일만 첨부하고
질문을 입력하지 않으면 `첨부한 자료의 핵심 내용을 분석해 주세요.`를 기본 질문으로 사용합니다.

기존 JSON 채팅 API의 호환성은 유지됩니다. 첨부하지 않으면 페르소나 생성 시 연결했던
기본 문서를 사용하고, 채팅에서 새 파일을 첨부하면 해당 요청에 한해 새 문서를 우선 사용합니다.
