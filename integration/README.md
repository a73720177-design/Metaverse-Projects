# 공통 서비스 통합 안내

공통 main 병합 전에 팀별로 해야 할 작업과 우선순위는 [공통 main 병합 전 체크리스트](./PRE_MAIN_CHECKLIST.md)를 확인합니다.

각 팀 코드를 한 프로세스에 섞지 않고 다음 주소 계약으로 연결합니다.

```text
React + Vite :5173 → Backend :8000 → LLM Service :8001 → Ollama :11434
                              └────→ DB / MinIO / Vector DB
```

## 현재 판단

| 영역 | 실제 상태 | 공통 main 반영 기준 |
|---|---|---|
| Frontend | React + Vite 코드가 공통 `main`에 병합됨 | PR #33 기준 실제 Backend 계약 검증 |
| Backend | JWT·소유권·문서 파싱·PostgreSQL·MinIO·LLM HTTP 경계 구현 | 실제 인프라 E2E 검증 |
| LLM | legacy와 정식 v1 API가 공통 `main`에 병합됨 | Ollama 실모델 검증 후 v1 전환 판단 |
| DB | migration `001~004`와 PostgreSQL Repository 구현 | 별도 테스트 DB에서 skip 없는 검증 |

## 통합 상태 확인

```powershell
Copy-Item integration\.env.example integration\.env
python integration\check_services.py
```

출력의 상태 의미:

- `ok`: 해당 주소에 연결됨
- `unavailable`: 서비스가 꺼져 있거나 주소·방화벽이 맞지 않음
- `not_configured`: 아직 팀 계약이 확정되지 않음
- `invalid_config`: 포트나 endpoint 형식이 잘못됨

기본적으로 Frontend·Backend·LLM·Ollama·PostgreSQL·MinIO가 모두 필수입니다. 하나라도 연결되지 않으면 종료 코드 1을 반환합니다. 부분 점검이 필요하면 `integration/.env`의 `REQUIRED_SERVICES`를 쉼표 목록으로 조정합니다. 주소에는 비밀번호나 API 키를 넣지 않습니다.

`CHECK_TIMEOUT_SECONDS`는 각 연결의 제한 시간입니다. PostgreSQL은 `DB_HOST`/`DB_PORT`, MinIO는 `MINIO_ENDPOINT`를 사용해 TCP 연결을 확인합니다. 이 점검은 인증·migration·버킷 권한까지 보장하지 않으므로 이후 팀별 통합 테스트가 필요합니다.

## 권장 병합 순서

1. 각 작업 브랜치를 해당 팀 main에 PR로 병합합니다.
2. 팀 main에서 단독 실행과 테스트를 확인합니다.
3. 공통 `main`에서 Backend·LLM·Frontend 의존성을 각각 설치합니다.
4. Ollama·PostgreSQL·MinIO를 먼저 기동합니다.
5. LLM → Backend → Frontend 순서로 기동합니다.
6. 이 상태 점검 도구로 여섯 서비스를 확인합니다.
7. 별도 테스트 DB에서 migration과 Repository 테스트를 실행합니다.

병합이나 rebase는 자동으로 수행하지 않습니다. 충돌이 예상되면 각 팀 담당자가 변경 파일을 확인하고 PR에서 해결합니다.
