# PostgreSQL DB 연동

## ERD

```mermaid
erDiagram
    AGENTS ||--o{ REVIEWS : writes
    DOCUMENTS ||--o{ REVIEWS : receives

    AGENTS {
        UUID agent_id PK
        TEXT name
        TEXT description
        TEXT role
        JSONB expertise
        JSONB evaluation_style
        TIMESTAMPTZ created_at
        TIMESTAMPTZ updated_at
    }

    DOCUMENTS {
        UUID document_id PK
        TEXT filename
        TEXT document_type
        TEXT bucket
        TEXT object_key
        JSONB sections
        TEXT full_text
        TIMESTAMPTZ created_at
    }

    REVIEWS {
        UUID review_id PK
        UUID agent_id FK
        UUID document_id FK
        JSONB claims
        JSONB feedback
        JSONB questions
        TIMESTAMPTZ created_at
    }
```

## 연결 설정

`backend/.env`에 비밀번호를 포함한 연결 주소를 설정합니다.

```env
DATABASE_URL=postgresql+asyncpg://사용자:비밀번호@localhost:5432/qwendb
```

`.env`는 Git에 커밋하지 않습니다.

MinIO도 같은 파일에서 설정합니다.

```env
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=접근키
MINIO_SECRET_KEY=비밀키
MINIO_BUCKET=documents
MINIO_SECURE=false
```

## 테이블 생성

- 개발 서버 시작 시 `app.db.database.init_db()`가 없는 테이블을 생성합니다.
- DBeaver에서는 `database/001_initial_schema.sql`을 실행할 수 있습니다.

## Repository 사용

- `PostgresAgentRepository`: 평가자 `save/get`
- `PostgresDocumentRepository`: 문서 `save/get`
- `PostgresReviewRepository`: 리뷰 `save/get`

`app/dependencies.py`가 위 구현을 서비스에 주입하므로 Controller나 Service에서 DB 라이브러리를 직접 가져오지 않습니다.

## 확인

```cmd
python -m pytest tests/test_postgres_repositories.py -q
```

저장 순서는 외래키 관계 때문에 평가자, 문서, 리뷰 순서입니다.
