# PostgreSQL 및 파일 저장소 연동

백엔드는 외부 인프라가 없어도 개발할 수 있도록 기본값을 `memory + local`로 사용합니다.
DB 팀의 PostgreSQL과 MinIO가 준비되면 `.env`의 모드만 변경합니다.

## 실행 모드

| 환경 변수 | 개발 기본값 | 팀 통합 시 값 | 역할 |
|---|---|---|---|
| `REPOSITORY_MODE` | `memory` | `postgres` | 모델 데이터 저장 위치 |
| `OBJECT_STORAGE_MODE` | `local` | `minio` | 업로드 원본 파일 저장 위치 |
| `DB_AUTO_CREATE` | `false` | 필요할 때만 `true` | 시작 시 SQLAlchemy 테이블 자동 생성 |

일반 백엔드 개발은 다음 설정으로 충분합니다.

```env
REPOSITORY_MODE=memory
OBJECT_STORAGE_MODE=local
DB_AUTO_CREATE=false
```

## PostgreSQL 연결

팀 DB와 통합할 때만 로컬 `backend/.env`에 다음 값을 설정합니다.

```env
REPOSITORY_MODE=postgres
DATABASE_URL=postgresql://사용자:비밀번호@localhost:5432/qwendb
DB_AUTO_CREATE=false
```

`postgresql://` 주소는 백엔드에서 `postgresql+asyncpg://`로 자동 변환합니다. 비밀번호가
포함된 `.env`는 Git에 커밋하지 않습니다.

Python 3.14에서는 빌드 오류가 있는 `asyncpg 0.30.0` 대신 3.14 wheel을 제공하는
`asyncpg 0.31.0`과 `greenlet 3.5.5`를 사용합니다.

문서 저장 구조는 `documents`, `document_files`, `document_chunks`로 분리합니다.

- `documents`: 문서 기본 정보와 전체 텍스트
- `document_files`: MinIO 또는 로컬 저장소의 bucket, object key, content type
- `document_chunks`: 순서가 있는 문서 구간과 확장 metadata

새 DB는 `database/001_initial_schema.sql`을 적용합니다. 기존 단일 `documents` 구조에서
전환할 때는 백업 후 `database/002_split_document_storage.sql`을 적용합니다. 이 migration은
기존 파일 메타데이터와 sections를 새 테이블로 옮긴 다음 이전 컬럼을 제거합니다.
`DB_AUTO_CREATE=true`는 개인 개발 DB에서만 사용하고 공유 DB는 버전 관리 SQL을 사용합니다.

적용 순서:

1. 대상 DB를 백업합니다.
2. 별도 테스트 DB에 `002_split_document_storage.sql`을 먼저 실행합니다.
3. 인증 기능을 사용할 DB에는 `003_add_users.sql`을 실행합니다.
4. 리소스 소유권을 적용할 DB에는 `004_add_resource_ownership.sql`을 실행합니다.
5. 이전된 `document_files`, `document_chunks`의 개수와 내용을 확인합니다.
6. 기존 리소스의 `owner_id=NULL` 유지 또는 소유자 배정 정책을 확인합니다.
7. 동일 SQL을 한 번 더 실행해 재실행 안전성을 확인합니다.
8. 검증 후 공유 DB에 적용합니다.

## MinIO 연결

```env
OBJECT_STORAGE_MODE=minio
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=개별_접근키
MINIO_SECRET_KEY=개별_비밀키
MINIO_BUCKET=documents
MINIO_SECURE=false
```

MinIO 모드에서는 endpoint, access key, secret key가 모두 필요합니다. 기본 관리자 계정은
코드에 넣지 않습니다. 로컬 모드의 파일은 기본적으로 `backend/uploads/objects`에 저장됩니다.
원본 파일의 object key는 `{document_id}/original{suffix}` 형식입니다.

예시:

```text
12345678-1234-5678-1234-567812345678/original.pdf
```

## 테스트

기본 테스트는 실제 팀 DB를 변경하지 않습니다.

```powershell
cd C:\meta_project\backend
python -m pytest -q
```

Repository 통합 테스트는 별도의 테스트 DB 주소를 지정했을 때만 실행됩니다.
설정 예시는 `backend/.env.test.example`에 있습니다.

```powershell
$env:TEST_DATABASE_URL="postgresql://사용자:비밀번호@localhost:5432/qwendb_test"
python -m pytest tests/test_postgres_repositories.py -q
```

공유 DB나 운영 DB를 `TEST_DATABASE_URL`로 사용하지 마세요. 이 테스트는 데이터를 생성합니다.
