# 공통 서비스 통합 안내

각 팀 코드를 한 프로세스에 섞지 않고 다음 주소 계약으로 연결합니다.

```text
React + Vite :5173 → Backend :8000 → LLM Service :8001 → Ollama :11434
                              └────→ DB / MinIO / Vector DB
```

## 현재 판단

| 영역 | 실제 상태 | 공통 main 반영 기준 |
|---|---|---|
| Frontend | 팀 main과 작업 브랜치에 코드가 아직 없음 | React + Vite 코드는 `frontend/`에 배치 |
| Backend | API·문서 파싱·LLM HTTP 경계 구현 | `backend/` 유지 |
| LLM | `kunhee-workspace`의 `llm-service/`에 실행 코드 존재 | 검토 후 `LLM-main`, 이후 공통 main에 병합 |
| DB | `qwendb` 접속과 문서 테이블 2개 확인, 저장 코드는 실험 단계 | Repository 또는 독립 API로 정리 후 병합 |

## 통합 상태 확인

```powershell
Copy-Item integration\.env.example integration\.env
python integration\check_services.py
```

출력의 상태 의미:

- `ok`: 해당 주소에 연결됨
- `unavailable`: 서비스가 꺼져 있거나 주소·방화벽이 맞지 않음
- `not_configured`: 아직 팀 계약이 확정되지 않음

Backend와 LLM은 필수 점검 대상이므로 둘 중 하나라도 연결되지 않으면 종료 코드 1을 반환합니다. Frontend·Ollama·DB 상태도 함께 표시하지만 서로의 내부 코드를 수정하지는 않습니다.

## 권장 병합 순서

1. 각 작업 브랜치를 해당 팀 main에 PR로 병합합니다.
2. 팀 main에서 단독 실행과 테스트를 확인합니다.
3. `LLM-main`을 공통 main에 병합하고 `llm-service/` 경로를 유지합니다.
4. `Backend-main`을 공통 main에 병합하고 `backend/` 경로를 유지합니다.
5. Frontend 코드를 `frontend/` 경로로 병합합니다.
6. DB는 실험 파일을 바로 병합하지 않고 실행 가능한 저장 계층으로 정리한 뒤 병합합니다.
7. 공통 main에서 이 상태 점검 도구를 실행합니다.

병합이나 rebase는 자동으로 수행하지 않습니다. 충돌이 예상되면 각 팀 담당자가 변경 파일을 확인하고 PR에서 해결합니다.
