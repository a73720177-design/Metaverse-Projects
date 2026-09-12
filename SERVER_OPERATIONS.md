# 서버 부팅·재부팅·안전 종료 가이드

이 문서는 Windows PowerShell에서 Metaverse Projects의 로컬 개발 서버를 실행하고, 상태를 확인하고, 데이터 손상 없이 종료하는 절차를 설명합니다.

## 서비스 구성과 포트

| 서비스 | 포트 | 상태 확인 |
|---|---:|---|
| Frontend (Vite) | 5173 | <http://localhost:5173> |
| Backend (FastAPI) | 8000 | <http://localhost:8000/health> |
| LLM Service (FastAPI) | 8001 | <http://localhost:8001/health> |
| Ollama | 11434 | <http://localhost:11434/api/tags> |
| PostgreSQL | 5432 | Docker healthcheck |
| MinIO API / Console | 9000 / 9001 | Docker healthcheck / <http://localhost:9001> |

권장 시작 순서는 `PostgreSQL·MinIO → Ollama → LLM Service → Backend → Frontend`입니다. 종료할 때는 반대 순서를 사용합니다.

## 1. 현재처럼 준비가 끝난 PC에서 평소 실행

다음 항목이 이미 준비되어 있다면 가상환경 생성, 패키지 설치, 모델 다운로드와 `.env` 복사를 다시 하지 않습니다.

- `backend/.venv`와 `llm-service/.venv`가 존재함
- `backend/.env`, `llm-service/.env`, 루트 `.env.local`이 존재함
- 루트 `node_modules`가 설치되어 있음
- Ollama에 `qwen3:4b`, `bge-m3`가 설치되어 있음
- 실제 DB 모드라면 Docker Desktop이 실행되어 있음

### 1-1. 준비 상태 빠른 확인

```powershell
Set-Location C:\meta_projects

Test-Path backend\.venv\Scripts\python.exe
Test-Path llm-service\.venv\Scripts\python.exe
Test-Path backend\.env
Test-Path llm-service\.env
Test-Path node_modules
ollama list
```

`Test-Path` 결과는 모두 `True`여야 합니다. `.env.local`은 Frontend 설정에 따라 없을 수도 있으므로 루트 `.env.example`과 현재 Vite 설정을 함께 확인합니다.

### 1-2. PostgreSQL·MinIO 시작

Backend가 실제 DB와 MinIO를 사용하도록 설정된 경우에만 실행합니다.

```powershell
Set-Location C:\meta_projects
docker compose up -d postgres minio
docker compose ps
```

`backend/.env`가 아래 개발 모드라면 이 단계는 건너뜁니다.

```env
REPOSITORY_MODE=memory
OBJECT_STORAGE_MODE=local
```

### 1-3. Ollama 시작

Ollama 데스크톱 앱이 실행 중이면 추가 명령이 필요하지 않습니다. 연결 여부만 확인합니다.

```powershell
Invoke-RestMethod http://localhost:11434/api/tags
```

연결되지 않을 때만 별도 PowerShell 창에서 실행합니다.

```powershell
ollama serve
```

### 1-4. LLM Service 시작 — PowerShell 창 1

가상환경을 다시 활성화하지 않고 가상환경의 Python을 직접 호출해도 됩니다.

```powershell
Set-Location C:\meta_projects\llm-service
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8001
```

### 1-5. Backend 시작 — PowerShell 창 2

```powershell
Set-Location C:\meta_projects\backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 1-6. Frontend 시작 — PowerShell 창 3

```powershell
Set-Location C:\meta_projects
npm run dev -- --host 0.0.0.0
```

### 1-7. 실행 완료 확인 — PowerShell 창 4

각 서버가 시작된 뒤 다음 순서로 확인합니다.

```powershell
Invoke-RestMethod http://localhost:11434/api/tags
Invoke-RestMethod http://localhost:8001/health
Invoke-RestMethod http://localhost:8000/health
Invoke-RestMethod http://localhost:8000/health/services
```

마지막으로 브라우저에서 <http://localhost:5173>을 엽니다. 통합 점검 설정이 이미 준비되어 있다면 다음 명령도 실행합니다.

```powershell
Set-Location C:\meta_projects
python integration\check_services.py
```

### 평소 실행 요약

```text
1. Docker Desktop 확인 — 실제 DB 모드일 때만
2. docker compose up -d postgres minio — 실제 DB 모드일 때만
3. Ollama 연결 확인 또는 ollama serve
4. LLM Service 실행
5. Backend 실행
6. Frontend 실행
7. health 및 integration 점검
```

## 2. 최초 실행 준비

이미 가상환경과 `.env` 파일을 만든 경우 이 단계는 건너뜁니다.

### Ollama 모델 준비

```powershell
ollama pull qwen3:4b
ollama pull bge-m3
```

### LLM Service 준비

```powershell
Set-Location C:\meta_projects\llm-service
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
deactivate
```

### Backend 준비

```powershell
Set-Location C:\meta_projects\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
deactivate
```

`backend/.env`의 `JWT_SECRET_KEY`에는 개발 환경에서도 충분히 긴 임의 문자열을 설정합니다. 실제 DB·MinIO 비밀번호와 토큰은 `.env`에만 두고 Git에 올리지 않습니다.

### Frontend 준비

```powershell
Set-Location C:\meta_projects
npm install
Copy-Item .env.example .env.local
```

`Copy-Item`이 이미 존재한다는 오류를 내면 기존 `.env` 또는 `.env.local`을 덮어쓰지 말고 내용을 확인합니다.

## 3. 전체 서버 부팅 상세

각 서비스는 별도의 PowerShell 창에서 실행합니다. 명령을 실행한 창을 닫으면 해당 서비스도 종료될 수 있습니다.

### 2-1. PostgreSQL과 MinIO

실제 DB·MinIO를 사용하는 경우에만 실행합니다.

```powershell
Set-Location C:\meta_projects
docker compose up -d postgres minio
docker compose ps
```

Backend가 `REPOSITORY_MODE=memory`, `OBJECT_STORAGE_MODE=local`이면 PostgreSQL과 MinIO 없이도 실행할 수 있습니다.

### 2-2. Ollama

Ollama 데스크톱 앱이 이미 실행 중이면 `ollama serve`를 다시 실행하지 않습니다.

```powershell
ollama serve
```

다른 PowerShell 창에서 모델 설치 상태를 확인합니다.

```powershell
ollama list
Invoke-RestMethod http://localhost:11434/api/tags
```

### 2-3. LLM Service

```powershell
Set-Location C:\meta_projects\llm-service
.\.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --host 0.0.0.0 --port 8001
```

확인:

```powershell
Invoke-RestMethod http://localhost:8001/health
```

### 2-4. Backend

```powershell
Set-Location C:\meta_projects\backend
.\.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

확인:

```powershell
Invoke-RestMethod http://localhost:8000/health
Invoke-RestMethod http://localhost:8000/health/services
```

### 2-5. Frontend

```powershell
Set-Location C:\meta_projects
npm run dev -- --host 0.0.0.0
```

브라우저에서 <http://localhost:5173>을 엽니다.

## 4. 전체 상태 점검

최초 한 번만 점검 설정을 복사합니다.

```powershell
Set-Location C:\meta_projects
Copy-Item integration\.env.example integration\.env
```

이후 전체 상태 점검:

```powershell
Set-Location C:\meta_projects
python integration\check_services.py
```

PostgreSQL이나 MinIO를 사용하지 않는 로컬 모드라면 `integration/.env`의 `REQUIRED_SERVICES`에서 사용하지 않는 서비스를 제외합니다.

포트 점유 상태는 다음 명령으로 확인할 수 있습니다.

```powershell
Get-NetTCPConnection -State Listen -LocalPort 5173,8000,8001,11434,5432,9000,9001 |
    Select-Object LocalAddress, LocalPort, OwningProcess
```

프로세스 이름 확인:

```powershell
$processId = (Get-NetTCPConnection -State Listen -LocalPort 8000).OwningProcess
Get-Process -Id $processId
```

## 5. 안전한 종료

### 기본 원칙

- 실행 중인 요청과 파일 업로드가 끝난 뒤 종료합니다.
- 각 실행 창에서 `Ctrl+C`를 한 번 눌러 정상 종료를 기다립니다.
- 종료 로그와 PowerShell 프롬프트가 돌아오기 전에 창을 강제로 닫지 않습니다.
- PostgreSQL·MinIO 볼륨을 보존하려면 `docker compose down -v`를 사용하지 않습니다.

### 4-1. Frontend 종료

Frontend를 실행한 PowerShell 창에서:

```text
Ctrl+C
```

### 4-2. Backend 종료

진행 중인 업로드·채팅 요청이 끝난 뒤 Backend 창에서:

```text
Ctrl+C
```

### 4-3. LLM Service 종료

생성 중인 응답이 끝난 뒤 LLM Service 창에서:

```text
Ctrl+C
```

### 4-4. Ollama 종료

직접 `ollama serve`를 실행했다면 해당 창에서:

```text
Ctrl+C
```

Ollama 데스크톱 앱으로 실행했다면 Windows 알림 영역의 Ollama 아이콘에서 종료합니다.

### 4-5. PostgreSQL과 MinIO 종료

컨테이너와 데이터를 삭제하지 않고 멈춥니다.

```powershell
Set-Location C:\meta_projects
docker compose stop postgres minio
docker compose ps
```

컨테이너 네트워크까지 정리하되 데이터 볼륨을 보존하려면 다음 명령을 사용할 수 있습니다.

```powershell
docker compose down
```

> `docker compose down -v`는 PostgreSQL과 MinIO 데이터 볼륨을 삭제하므로 초기화가 명확히 필요한 경우가 아니면 사용하지 않습니다.

### 종료 확인

아래 결과가 비어 있으면 관련 포트가 모두 해제된 것입니다.

```powershell
Get-NetTCPConnection -State Listen -LocalPort 5173,8000,8001,11434,5432,9000,9001 `
    -ErrorAction SilentlyContinue
```

## 6. 전체 서버 재부팅

1. 새 업로드와 채팅 요청을 중지합니다.
2. `Frontend → Backend → LLM Service → Ollama → PostgreSQL·MinIO` 순서로 안전하게 종료합니다.
3. 종료 확인 명령으로 기존 포트가 해제됐는지 확인합니다.
4. 5432·9000·9001 포트가 해제되었으면 PostgreSQL과 MinIO를 시작합니다.
5. `docker compose ps`에서 두 컨테이너가 healthy인지 확인합니다.
6. Ollama를 시작하고 `/api/tags`를 확인합니다.
7. LLM Service를 시작하고 `/health`를 확인합니다.
8. Backend를 시작하고 `/health/services`를 확인합니다.
9. 마지막으로 Frontend를 시작합니다.
10. `python integration\check_services.py`로 전체 연결을 검증합니다.

재부팅 중에는 이전 프로세스가 완전히 종료되기 전에 같은 포트로 새 프로세스를 실행하지 않습니다.

## 7. 비정상 종료와 포트 충돌 대응

먼저 포트를 점유한 프로세스를 확인합니다.

```powershell
$processId = (Get-NetTCPConnection -State Listen -LocalPort 8000).OwningProcess
Get-Process -Id $processId
```

해당 프로세스가 이 프로젝트의 이전 Backend 프로세스인지 확인한 후에만 정상 종료를 요청합니다.

```powershell
Stop-Process -Id $processId
Wait-Process -Id $processId -ErrorAction SilentlyContinue
```

정상 종료가 되지 않을 때만 마지막 수단으로 강제 종료합니다.

```powershell
Stop-Process -Id $processId -Force
```

포트별 일반적인 원인:

| 증상 | 확인 사항 |
|---|---|
| 5173 충돌 | 이전 Vite 또는 Node 프로세스 |
| 8000 충돌 | 이전 Backend Uvicorn 프로세스 |
| 8001 충돌 | 이전 LLM Service Uvicorn 프로세스 |
| 11434 충돌 | Ollama 앱이 실행 중인데 `ollama serve`를 다시 실행함 |
| 5432 충돌 | 로컬 PostgreSQL과 Docker PostgreSQL이 동시에 실행됨 |
| 9000 충돌 | 기존 MinIO 또는 다른 애플리케이션 |

`Get-Process python`, `Get-Process node`처럼 이름만으로 모든 프로세스를 일괄 종료하지 않습니다. 다른 프로젝트나 사용자 작업까지 종료될 수 있으므로 반드시 포트와 PID를 확인합니다.

## 8. 장애 발생 시 점검 순서

1. Backend `/health`가 정상인지 확인합니다.
2. Backend `/health/services`에서 실패한 하위 서비스를 찾습니다.
3. LLM Service `/health`와 Ollama `/api/tags`를 확인합니다.
4. `docker compose ps`에서 PostgreSQL·MinIO 상태를 확인합니다.
5. Backend와 LLM Service의 실행 창에서 최초 오류 로그를 확인합니다.
6. `.env`의 URL, 포트, Repository/Object Storage 모드를 확인합니다.
7. 수정 후 전체를 무조건 재시작하기보다 실패한 하위 서비스부터 재시작합니다.

## 9. 종료 전 체크리스트

- [ ] 파일 업로드·파싱이 끝났습니다.
- [ ] LLM 답변 생성이 끝났습니다.
- [ ] 필요한 변경 사항을 저장했습니다.
- [ ] Frontend, Backend, LLM Service에 `Ctrl+C` 정상 종료를 요청했습니다.
- [ ] PostgreSQL·MinIO는 `stop` 또는 볼륨을 보존하는 `down`으로 종료했습니다.
- [ ] 주요 포트가 해제됐는지 확인했습니다.
- [ ] 데이터 삭제 명령인 `docker compose down -v`를 사용하지 않았습니다.
