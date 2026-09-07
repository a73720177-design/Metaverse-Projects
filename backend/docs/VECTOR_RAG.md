# BGE-M3 벡터 RAG

기본값은 `RAG_MODE=lexical`입니다. 기존 DB에 pgvector를 준비한 후 명시적으로 켭니다.
백엔드는 별도 임베딩 클라이언트로 Ollama `/api/embed`를 호출합니다.
기존 답변 생성용 LLM 서비스 계약은 유지합니다.

## 활성화 순서

1. PostgreSQL을 논리 백업하고 별도 테스트 DB에 복원 가능한지 확인합니다.
2. pgvector가 설치된 PostgreSQL 16 환경을 준비합니다. 기존 Alpine 볼륨을
   Debian 기반 이미지에 곧바로 연결하지 말고 별도 볼륨에 백업을 복원하여
   로케일/정렬 규칙 및 데이터 무결성을 검증합니다. 기존 볼륨은 보관합니다.
3. `008_add_document_embeddings.sql`을 `psql -v ON_ERROR_STOP=1 -1 -f ...`로 적용합니다.
   확장 설치가 없는 기존 DB에서 이 SQL은 실패합니다. 코드가 자동 적용하지 않습니다.
4. backend/.env에 아래 설정을 추가합니다.

```dotenv
RAG_MODE=vector
OLLAMA_EMBEDDING_MODEL=bge-m3:latest
OLLAMA_EMBEDDING_URL=http://127.0.0.1:11434
```

5. backend 디렉터리에서 `.venv\Scripts\python.exe -m scripts.backfill_document_embeddings`를
   실행합니다. 기존 청크의 내용과 ID는 유지하며 8개씩 처리합니다.
   실패하면 종료 코드 1을 반환하며, 재실행 시 완료된 동일 내용·모델은 건너뜁니다.
6. 백엔드를 재시작하고 실제 회원 계정으로 자료를 첨부한 채팅을 검증합니다.

```sql
SELECT count(*) AS total, count(embedding) AS embedded FROM document_chunks;
SELECT embedding_model, count(*) FROM document_chunks GROUP BY embedding_model;
```

## 동작과 제한

- BGE-M3 1024차원, 유한한 값과 0이 아닌 벡터를 검증합니다.
- 문서 저장 후 임베딩합니다. 실패해도 업로드는 유지하며 로그를 남깁니다.
- 현재 저장된 문서 구간 전체를 임베딩합니다. 컨텍스트 초과 시 조용히 자르지 않고
  실패 처리합니다. 긴 구간의 재청킹은 별도 작업이 필요합니다.
- 검색은 회원 소유권과 허용된 문서 ID를 SQL에서 함께 검사합니다.
- 연결된 문서 전체에서 코사인 거리로 후보를 찾고 가장 가까운 문서 한 개의
  최대 3개 구간, 4000자까지 답변 생성에 전달합니다.
- 서로 다른 모델의 벡터와 내용이 바뀐 벡터는 검색에서 제외합니다.
- 벡터 미등록 또는 검색 실패 시 기존 키워드 검색을 사용합니다. 점수 혼합 방식의
  하이브리드는 아직 구현하지 않았습니다.
- `RAG_MODE=lexical`로 되돌리면 마이그레이션을 되돌리지 않고 기존 검색을 사용할 수 있습니다.
- 같은 모델 태그의 내용이 바뀌면 태그 문자열 비교로 감지할 수 없으므로 모델을 고정하고
  변경 시 해당 임베딩을 무효화한 뒤 백필해야 합니다.

SQL은 파라미터 바인딩과 `CAST(... AS vector)`를 사용합니다. 일반 ORM 조회는
임베딩 컬럼에 의존하지 않으므로 마이그레이션 전에도 기존 기능을 사용할 수 있습니다.
Python pgvector 패키지는 필요하지 않습니다.

공식 API: https://docs.ollama.com/api/embed
pgvector: https://github.com/pgvector/pgvector
