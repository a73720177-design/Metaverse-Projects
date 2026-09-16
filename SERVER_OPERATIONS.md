# Metaverse Projects 실행·운영 가이드

이 문서는 Windows PowerShell에서 프로젝트를 실행하는 방법을 **현재 데스크톱**과 **노트북**으로 구분해 설명합니다.

> PowerShell 실행 정책 문제를 피하기 위해 `Activate.ps1`을 사용하지 않습니다. Python은 각 가상환경의 `python.exe`를 직접 실행하고, npm은 `npm.cmd`를 사용합니다.

## 공통 서비스와 포트

| 서비스 | 포트 | 확인 주소 |
|---|---:|---|
| Frontend (Vite) | 5173 | <http://localhost:5173> |
| Backend (FastAPI) | 8000 | <http://localhost:8000/health> |
| LLM Service (FastAPI) | 8001 | <http://localhost:8001/health> |
| Ollama | 11434 | <http://localhost:11434/api/tags> |
| PostgreSQL (선택) | 5432 | `docker compose ps` |
| MinIO API / Console (선택) | 9000 / 9001 | <http://localhost:9001> |

시작 순서는 `Ollama → LLM Service → Backend → Frontend`, 종료는 반대 순서입니다.

---

# A. 현재 데스크톱에서 실행

## A-1. 확인된 데스크톱 환경

- 컴퓨터: `DESKTOP-V0H7GMG`
- 프로젝트 경로: `C:\meta_project`
- CPU: AMD Ryzen 7 9800X3D (8코어/16스레드)
- RAM: 약 32GB
- GPU: NVIDIA GeForce RTX 5070 Ti
- Python: 3.14.7
- Node.js: 24.19.0
- npm: 11.17.0
- Docker Desktop/Engine: 29.7.2
- Ollama 텍스트 모델: `qwen3:4b` (임베딩은 `bge-m3`)
- 실행 전 `git branch --show-current`와 `git status --short`로 현재 브랜치와 변경사항을 확인합니다.

현재 데스크톱 Backend는 Docker의 PostgreSQL과 MinIO를 사용하는 모드입니다.

```env
REPOSITORY_MODE=postgres
OBJECT_STORAGE_MODE=minio
RAG_MODE=lexical
LLM_API_PREFIX=/api/v1
```

## A-2. 최초 1회 준비

PowerShell을 열고 프로젝트 루트를 지정합니다.

```powershell
$ProjectRoot = 'C:\meta_project'
Set-Location $ProjectRoot
```

### Backend 준비

기존 가상환경을 유지하면서 최신 의존성을 설치합니다.

```powershell
& "$ProjectRoot\backend\.venv\Scripts\python.exe" -m pip install -r "$ProjectRoot\backend\requirements.txt"
```

가상환경이 없을 때만 새로 만듭니다.

```powershell
python -m venv "$ProjectRoot\backend\.venv"
& "$ProjectRoot\backend\.venv\Scripts\python.exe" -m pip install --upgrade pip
& "$ProjectRoot\backend\.venv\Scripts\python.exe" -m pip install -r "$ProjectRoot\backend\requirements.txt"
```

`backend\.env`가 없다면 예시 파일을 복사합니다. 이미 있으면 덮어쓰지 않습니다.

```powershell
if (-not (Test-Path "$ProjectRoot\backend\.env")) {
    Copy-Item "$ProjectRoot\backend\.env.example" "$ProjectRoot\backend\.env"
}
```

### LLM Service 준비

```powershell
if (-not (Test-Path "$ProjectRoot\llm-service\.venv\Scripts\python.exe")) {
    python -m venv "$ProjectRoot\llm-service\.venv"
}
& "$ProjectRoot\llm-service\.venv\Scripts\python.exe" -m pip install --upgrade pip
& "$ProjectRoot\llm-service\.venv\Scripts\python.exe" -m pip install -r "$ProjectRoot\llm-service\requirements.txt"

if (-not (Test-Path "$ProjectRoot\llm-service\.env")) {
    Copy-Item "$ProjectRoot\llm-service\.env.example" "$ProjectRoot\llm-service\.env"
}
```

데스크톱의 `llm-service\.env` 권장값:

```env
LLM_PROVIDER=ollama
OLLAMA_HOST=http://127.0.0.1:11434
OLLAMA_MODEL=qwen3:4b
OLLAMA_CHAT_MODEL=qwen3:4b
OLLAMA_REVIEW_MODEL=qwen3:4b
OLLAMA_QUESTION_MODEL=qwen3:4b
OLLAMA_SUMMARY_MODEL=qwen3:4b
LLM_MAX_CONCURRENT_GENERATIONS=1
OLLAMA_KEEP_ALIVE=5m
```

### Frontend 준비

이 PC에서는 `npm` 대신 반드시 `npm.cmd`를 사용합니다.

```powershell
Set-Location $ProjectRoot
npm.cmd ci
```

`npm ci`는 `package-lock.json`을 기준으로 깨끗하게 설치합니다. 평소에는 다시 실행할 필요가 없습니다.

`.env.local`이 없을 때만 생성합니다.

```powershell
if (-not (Test-Path "$ProjectRoot\.env.local")) {
    Copy-Item "$ProjectRoot\.env.example" "$ProjectRoot\.env.local"
}
```

로컬 개발용 값:

```env
VITE_API_BASE_URL=/api-backend
```

### Ollama 확인

Ollama 데스크톱 앱이 실행 중이면 `ollama serve`를 별도로 실행하지 않습니다.

```powershell
ollama list
Invoke-RestMethod http://127.0.0.1:11434/api/tags
```

연결에 실패할 때만 Ollama 앱을 실행하거나 새 창에서 다음 명령을 실행합니다.

```powershell
ollama serve
```

`RAG_MODE=lexical`에서는 `bge-m3`가 필요하지 않습니다. Vector RAG를 쓸 때만 설치합니다.

```powershell
ollama pull bge-m3
```

## A-3. 평소 서버 실행

먼저 Docker Desktop을 실행하고 저장소 루트에서 PostgreSQL과 MinIO를 시작합니다.

```powershell
$ProjectRoot = 'C:\meta_project'
Set-Location $ProjectRoot
docker compose up -d postgres minio
docker compose ps
```

두 컨테이너가 모두 `healthy`가 된 후 아래 명령을 **서로 다른 PowerShell 창**에서 실행합니다. 최초 구성 또는 DB 스키마가 변경된 브랜치를 받은 직후에는 Backend보다 먼저 마이그레이션을 적용합니다.

```powershell
Set-Location "$ProjectRoot\backend"
& ".\.venv\Scripts\python.exe" scripts\apply_migrations.py --dry-run
& ".\.venv\Scripts\python.exe" scripts\apply_migrations.py --apply --confirm-database qwendb
```

### 데스크톱 창 1 — LLM Service

```powershell
$ProjectRoot = 'C:\meta_project'
Set-Location "$ProjectRoot\llm-service"
& ".\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

### 데스크톱 창 2 — Backend

```powershell
$ProjectRoot = 'C:\meta_project'
Set-Location "$ProjectRoot\backend"
& ".\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### 데스크톱 창 3 — Frontend

```powershell
$ProjectRoot = 'C:\meta_project'
Set-Location $ProjectRoot
npm.cmd run dev -- --host 127.0.0.1
```

브라우저에서 <http://127.0.0.1:5173>을 엽니다.

## A-4. 데스크톱 상태 확인

```powershell
Invoke-RestMethod http://127.0.0.1:11434/api/tags
Invoke-RestMethod http://127.0.0.1:8001/health
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/health/services
```

데스크톱 통합 점검은 PostgreSQL과 MinIO를 포함합니다. `integration\.env`의 값을 다음처럼 설정합니다. DB 비밀번호나 MinIO 키는 이 파일에 넣지 않습니다.

```env
FRONTEND_URL=http://127.0.0.1:5173
BACKEND_URL=http://127.0.0.1:8000
LLM_URL=http://127.0.0.1:8001
OLLAMA_URL=http://127.0.0.1:11434
CHECK_TIMEOUT_SECONDS=5
REQUIRED_SERVICES=frontend,backend,llm,ollama,postgresql,minio
DB_HOST=127.0.0.1
DB_PORT=5432
MINIO_ENDPOINT=127.0.0.1:9000
```

점검 실행:

```powershell
$ProjectRoot = 'C:\meta_project'
& "$ProjectRoot\backend\.venv\Scripts\python.exe" "$ProjectRoot\integration\check_services.py"
```

## A-5. 데스크톱 테스트

```powershell
$ProjectRoot = 'C:\meta_project'

Set-Location "$ProjectRoot\backend"
& ".\.venv\Scripts\python.exe" -m pytest -q

Set-Location "$ProjectRoot\llm-service"
& ".\.venv\Scripts\python.exe" -m pip install -r requirements-dev.txt
& ".\.venv\Scripts\python.exe" -m pytest -q

Set-Location $ProjectRoot
npm.cmd test
npm.cmd run build
```

---

# B. 노트북에서 실행

노트북에서는 프로젝트 경로와 성능이 데스크톱과 다를 수 있으므로, 경로를 먼저 지정하고 저부하 설정을 사용합니다. 아래 예시는 프로젝트가 `C:\meta_project`에 있을 때의 값입니다. 다른 경로라면 첫 줄만 바꿉니다.

## B-1. 노트북 권장 설정

```powershell
$ProjectRoot = 'C:\meta_project'
Set-Location $ProjectRoot
```

노트북에서는 Docker 없이 다음 Backend 모드를 권장합니다.

```env
REPOSITORY_MODE=memory
OBJECT_STORAGE_MODE=local
RAG_MODE=lexical
PRACTICE_MAX_CONCURRENT_PERSONAS=1
```

노트북의 `llm-service\.env` 권장값:

```env
LLM_PROVIDER=ollama
OLLAMA_HOST=http://127.0.0.1:11434
OLLAMA_MODEL=qwen3:4b
OLLAMA_CHAT_MODEL=qwen3:4b
OLLAMA_REVIEW_MODEL=qwen3:4b
OLLAMA_QUESTION_MODEL=qwen3:4b
OLLAMA_SUMMARY_MODEL=qwen3:4b
LLM_MAX_CONCURRENT_GENERATIONS=1
OLLAMA_KEEP_ALIVE=2m
OLLAMA_MAX_OUTPUT_TOKENS=1024
```

노트북에 모델이 없다면 최초 1회 설치합니다.

```powershell
ollama pull qwen3:4b
```

Vector RAG를 사용하지 않으면 `bge-m3`, PostgreSQL과 MinIO는 설치하지 않아도 됩니다.

## B-2. 노트북 최초 준비

`Activate.ps1`을 사용하지 않고 실행 파일을 직접 호출합니다.

```powershell
$ProjectRoot = 'C:\meta_project'

if (-not (Test-Path "$ProjectRoot\backend\.venv\Scripts\python.exe")) {
    python -m venv "$ProjectRoot\backend\.venv"
}
& "$ProjectRoot\backend\.venv\Scripts\python.exe" -m pip install -r "$ProjectRoot\backend\requirements.txt"

if (-not (Test-Path "$ProjectRoot\llm-service\.venv\Scripts\python.exe")) {
    python -m venv "$ProjectRoot\llm-service\.venv"
}
& "$ProjectRoot\llm-service\.venv\Scripts\python.exe" -m pip install -r "$ProjectRoot\llm-service\requirements.txt"

if (-not (Test-Path "$ProjectRoot\backend\.env")) {
    Copy-Item "$ProjectRoot\backend\.env.example" "$ProjectRoot\backend\.env"
}
if (-not (Test-Path "$ProjectRoot\llm-service\.env")) {
    Copy-Item "$ProjectRoot\llm-service\.env.example" "$ProjectRoot\llm-service\.env"
}

Set-Location $ProjectRoot
npm.cmd ci
```

## B-3. 노트북 실행

각 블록을 별도 PowerShell 창에서 실행합니다.

```powershell
# 창 1: LLM Service
$ProjectRoot = 'C:\meta_project'
Set-Location "$ProjectRoot\llm-service"
& ".\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

```powershell
# 창 2: Backend
$ProjectRoot = 'C:\meta_project'
Set-Location "$ProjectRoot\backend"
& ".\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

```powershell
# 창 3: Frontend
$ProjectRoot = 'C:\meta_project'
Set-Location $ProjectRoot
npm.cmd run dev -- --host 127.0.0.1
```

노트북에서도 <http://127.0.0.1:5173>으로 접속합니다.

## B-4. 노트북을 다른 기기에서 접속할 때

같은 LAN이나 Hamachi에서 접속해야 할 때만 세 서버의 `--host`를 `0.0.0.0`으로 바꿉니다.

```powershell
# LLM Service
& ".\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8001

# Backend
& ".\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8000

# Frontend
npm.cmd run dev -- --host 0.0.0.0
```

Windows 방화벽을 무작정 해제하지 말고, 필요한 포트만 개인 네트워크에 허용합니다. 외부 공유가 필요 없으면 항상 `127.0.0.1`을 사용합니다.

---

# C. PostgreSQL·MinIO 운영

이 절은 데스크톱 기본 구성입니다. 노트북에서는 팀 DB 작업이 꼭 필요한 경우에만 사용합니다.

Docker Desktop을 먼저 실행한 뒤:

```powershell
$ProjectRoot = 'C:\meta_project'
Set-Location $ProjectRoot
docker compose up -d postgres minio
docker compose ps
```

Docker Compose는 루트 `.env`, Backend는 `backend\.env`를 읽습니다. 두 파일의 PostgreSQL 비밀번호와 MinIO 자격증명은 반드시 같아야 합니다. 실제 값은 문서나 Git에 기록하지 않습니다.

```env
REPOSITORY_MODE=postgres
OBJECT_STORAGE_MODE=minio
DATABASE_URL=postgresql+asyncpg://qwen:<password>@127.0.0.1:5432/qwendb
MINIO_ENDPOINT=127.0.0.1:9000
MINIO_ACCESS_KEY=<access-key>
MINIO_SECRET_KEY=<secret-key>
MINIO_BUCKET=documents
MINIO_SECURE=false
```

마이그레이션은 Backend 시작 전에 실행합니다.

```powershell
$ProjectRoot = 'C:\meta_project'
Set-Location "$ProjectRoot\backend"
& ".\.venv\Scripts\python.exe" scripts\apply_migrations.py --dry-run
& ".\.venv\Scripts\python.exe" scripts\apply_migrations.py --apply --confirm-database qwendb
```

데이터를 보존하며 종료:

```powershell
Set-Location C:\meta_project
docker compose stop postgres minio
```

> `docker compose down -v`는 PostgreSQL과 MinIO 볼륨을 삭제합니다. 초기화가 명확히 필요한 경우 외에는 실행하지 않습니다.

---

# D. 공통 종료 및 문제 해결

## 정상 종료

Frontend, Backend, LLM Service를 실행한 각 PowerShell 창에서 `Ctrl+C`를 누릅니다. `ollama serve`를 직접 실행했다면 해당 창에서도 `Ctrl+C`를 누릅니다.

포트가 해제됐는지 확인합니다.

```powershell
Get-NetTCPConnection -State Listen -LocalPort 5173,8000,8001 `
    -ErrorAction SilentlyContinue
```

## 포트 충돌

```powershell
$serverProcessId = (Get-NetTCPConnection -State Listen -LocalPort 8000).OwningProcess
Get-Process -Id $serverProcessId
```

프로젝트 프로세스임을 확인한 후, 실행 창에 접근할 수 없을 때만 종료합니다.

```powershell
Stop-Process -Id $serverProcessId
```

`Get-Process python | Stop-Process` 또는 `Get-Process node | Stop-Process`처럼 모든 프로세스를 한꺼번에 종료하지 않습니다.

## 자주 발생하는 오류

| 증상 | 원인 | 해결 |
|---|---|---|
| `npm.ps1 ... scripts is disabled` | PowerShell 실행 정책 | `npm.cmd` 사용 |
| `Activate.ps1 cannot be loaded` | PowerShell 실행 정책 | 가상환경의 `python.exe` 직접 호출 |
| `No module named ...` | 가상환경 패키지 미설치 | 해당 서비스의 `python.exe -m pip install -r requirements.txt` |
| LLM Service가 Ollama에 연결하지 못함 | Ollama 미실행 | Ollama 앱 실행 후 `/api/tags` 확인 |
| `/api/v1/health`가 503 | 설정된 생성/임베딩 모델 누락 | `ollama list` 확인 후 필요한 모델 pull |
| Frontend는 열리지만 API 실패 | Backend 미실행 또는 잘못된 URL | Backend `:8000/health`, `.env.local` 확인 |
| `docker` 연결 오류 | Docker Desktop 미실행 | Docker Desktop 실행 후 `docker version` 확인 |
| 통합 점검에서 DB/MinIO 실패 | 컨테이너 미실행 또는 주소 불일치 | `docker compose ps`와 `integration\.env` 확인 |

## 최종 체크리스트

- [ ] `ollama list`에 사용할 생성 모델이 있습니다.
- [ ] `docker compose ps`에서 PostgreSQL과 MinIO가 `healthy`입니다.
- [ ] LLM Service `/health`가 응답합니다.
- [ ] Backend `/health`와 `/health/services`가 응답합니다.
- [ ] Frontend가 `127.0.0.1:5173`에서 열립니다.
- [ ] PowerShell에서는 `npm.cmd`를 사용했습니다.
- [ ] `.env`와 비밀값을 Git에 추가하지 않았습니다.
- [ ] 데스크톱과 노트북 설정을 서로 덮어쓰지 않았습니다.
