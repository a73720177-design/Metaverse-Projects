ALTER TABLE agents
ADD COLUMN IF NOT EXISTS owner_id UUID REFERENCES users(user_id) ON DELETE CASCADE;

ALTER TABLE documents
ADD COLUMN IF NOT EXISTS owner_id UUID REFERENCES users(user_id) ON DELETE CASCADE;

ALTER TABLE reviews
ADD COLUMN IF NOT EXISTS owner_id UUID REFERENCES users(user_id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS ix_agents_owner_id ON agents(owner_id);
CREATE INDEX IF NOT EXISTS ix_documents_owner_id ON documents(owner_id);
CREATE INDEX IF NOT EXISTS ix_reviews_owner_id ON reviews(owner_id);

-- 기존 행은 owner_id=NULL로 보존합니다. 소유자 확인 없이 임의 계정에 배정하지 않습니다.
-- 신규 API 요청은 인증된 user_id를 항상 저장하며 NULL인 기존 행에는 접근할 수 없습니다.
