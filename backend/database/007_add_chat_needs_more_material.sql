-- 유사도 임계값에 못 미쳐 "자료를 추가해 달라"고 응답한 메시지를 구분합니다.
-- LLM 서비스가 needs_more_material=true로 표시한 답변은 근거 자료 없이
-- 템플릿으로 생성되므로, 이력에서도 일반 답변과 구분되어야 합니다.
ALTER TABLE chat_messages
ADD COLUMN IF NOT EXISTS needs_more_material BOOLEAN NOT NULL DEFAULT FALSE;
