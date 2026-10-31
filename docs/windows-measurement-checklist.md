# Windows 측정 체크리스트 (논문 실험 1·2)

목표: 표 2(모델별 생성 시간)와 표 3(필터 단계별 기각 비율)을 채울 데이터를 모아서 Mac으로 가져오기.
명령은 모두 **PowerShell**에서, **저장소 루트 폴더**에서 실행한다.
`<backend>`, `<ollama>`는 0-3에서 찾은 컨테이너 이름으로 바꿔서 입력한다.

---

## 0. 준비

- [ ] **0-1. 바뀐 파일 두 개를 Windows PC로 옮기기** (git pull 또는 직접 복사)
  - `build/payload/backend/app/services/practice_service.py`
  - `build/payload/backend/scripts/measure_practice_filter.py`
- [ ] **0-2. 앱 실행:** 바탕화면의 'Metaverse 실행'을 누르고, 브라우저에 화면이 뜨는지 확인
- [ ] **0-3. 컨테이너 이름 확인**
  ```
  docker ps --format "{{.Names}}"
  ```
  - `backend`가 들어간 이름과 `ollama`가 들어간 이름을 적어 둔다.
  - `vllm`이 들어간 컨테이너가 있으면 GPU(vLLM) 모드다. 이 사실도 적어 둔다.
- [ ] **0-4. 설치된 모델 확인**
  ```
  docker exec <ollama> ollama list
  ```
  - `qwen3:4b`가 있어야 한다.
  - `qwen3.5:9b`가 있어야 9B 측정이 가능하다. 없으면 9B 측정은 건너뛰고 "9B 미설치"라고 기록한다.

## 1. 시연 데이터로 연습 기록 만들기 (앱 화면에서)

스크립트는 **가장 최근 연습 기록**을 그대로 다시 실행한다. 그래서 측정 직전에 아래 조건으로 한 번 생성해 둔다.

- [ ] 발표자료: `시연_예시자료/01_시연용_발표자료_캠퍼스_분리배출.pptx`와 `02_발표대본_캠퍼스_분리배출.pdf`
- [ ] 페르소나 3명. 각자 참고자료를 연결한다.
  - 기술 검토자 ← `03_페르소나_소스_기술검토자.pdf`
  - 운영·예산 ← `04_페르소나_소스_운영예산.pdf`
  - 학생경험 ← `05_페르소나_소스_학생경험.pdf`
- [ ] 페르소나당 질문 수 **5개**, 모델 **qwen3:4b**로 예상 질문 생성
- [ ] (선택) 생성된 질문 화면 **스크린샷** 1장. 포스터나 논문 그림 후보로 쓴다.

## 2. 측정 코드를 컨테이너에 넣기

- [ ] **2-1.** 바뀐 서비스 파일 복사
  ```
  docker cp build/payload/backend/app/services/practice_service.py <backend>:/app/app/services/practice_service.py
  ```
- [ ] **2-2.** 측정 스크립트 복사
  ```
  docker cp build/payload/backend/scripts/measure_practice_filter.py <backend>:/app/scripts/measure_practice_filter.py
  ```
- [ ] **2-3. 복사가 됐는지 확인:** `True`가 나와야 한다.
  ```
  docker exec <backend> python -c "print('filter_observer' in open('/app/app/services/practice_service.py', encoding='utf-8').read())"
  ```

## 3. 측정 실행

각 단계는 PC 사양에 따라 수십 분 걸릴 수 있다. 회차가 끝날 때마다 `{"run": 1, "seconds": ...}` 줄이 출력되면 정상이다.

- [ ] **3-1. 예열 (결과는 버림):** 첫 실행에는 모델 로딩 시간이 섞이므로 한 번 먼저 돌린다.
  ```
  docker exec <backend> python -m scripts.measure_practice_filter --model qwen3:4b --repeats 1 --out /tmp/warmup
  ```
- [ ] **3-2. 4B 본 측정**
  ```
  docker exec <backend> python -m scripts.measure_practice_filter --model qwen3:4b --repeats 3 --out /tmp/practice-filter-4b
  ```
  - 화면에 출력된 `run / seconds / generated` 줄 3개를 **그대로 복사해서 메모장에 저장**한다.
- [ ] **3-3. 9B 측정** (설치된 경우만): 9B도 예열 1회 후 본 측정을 한다.
  ```
  docker exec <backend> python -m scripts.measure_practice_filter --model qwen3.5:9b --repeats 1 --out /tmp/warmup-9b
  ```
  ```
  docker exec <backend> python -m scripts.measure_practice_filter --model qwen3.5:9b --repeats 3 --out /tmp/practice-filter-9b
  ```
  - 출력 줄 3개를 마찬가지로 메모장에 저장한다.
  - GPU(vLLM) 모드에서는 9B 요청이 실패하거나 다르게 처리될 수 있다. 오류가 나면 **오류 메시지 전체를 저장**한다.
- [ ] **3-4. 결과 폴더를 PC로 가져오기**
  ```
  docker cp <backend>:/tmp/practice-filter-4b ./practice-filter-4b
  ```
  ```
  docker cp <backend>:/tmp/practice-filter-9b ./practice-filter-9b
  ```

## 4. 측정 PC 사양 기록

- [ ] CPU
  ```
  Get-CimInstance Win32_Processor | Select-Object Name, NumberOfCores
  ```
- [ ] RAM
  ```
  Get-CimInstance Win32_ComputerSystem | Select-Object @{n='RAM_GB';e={[math]::Round($_.TotalPhysicalMemory/1GB)}}
  ```
- [ ] GPU: 명령이 없거나 오류가 나면 "NVIDIA GPU 없음"으로 기록한다.
  ```
  nvidia-smi --query-gpu=name,memory.total --format=csv
  ```
- [ ] Windows 버전, 그리고 vLLM 사용 여부(0-3에서 확인한 것)

## 5. 사람 판정 (시간이 되면, 30분 정도)

- [ ] 엑셀에서 `practice-filter-4b/review_sheet.csv`를 연다.
- [ ] 각 질문의 `unsupported_content(Y/N)` 열을 채운다.
  - **Y:** 질문이 **발표자료에 없는 사실·수치·주장**을 전제로 함. 예: 자료에 없는 "만족도 80%"를 언급
  - **N:** 자료에 있는 내용만 전제로 함. "~는 어떻게 검증했나요?"처럼 자료 내용을 묻는 질문은 N
  - 애매하면 `note` 열에 이유를 적는다.
- [ ] 판정 기준은 한 사람이 끝까지 일관되게 적용한다. 가능하면 두 사람이 나눠 보고 겹치는 몇 개를 비교한다.

## 6. 문제가 생기면

| 증상 | 조치 |
|---|---|
| `연습 기록이 없습니다` | 1단계(앱에서 질문 생성)를 먼저 한다 |
| 2-3에서 `False` | 2-1 복사 명령의 컨테이너 이름과 경로를 다시 확인한다 |
| `No module named scripts.measure_practice_filter` | 2-2 복사를 다시 한다 |
| 실행 중 연결 오류나 시간 초과 | 앱이 켜져 있는지 확인하고 해당 단계를 다시 실행한다. 오류 전문은 저장한다 |
| 앱을 재시작한 뒤 | 컨테이너가 새로 만들어졌을 수 있다. 2단계부터 다시 한다 |

---

## Mac으로 가져올 결과물

| # | 결과물 | 쓰는 곳 | 필수 |
|---|---|---|---|
| 1 | `practice-filter-4b/` 폴더 전체 (`summary.md`, `events.jsonl`, `review_sheet.csv`) | 표 3, 요약·결론 수치 | ✅ |
| 2 | 4B 실행 출력 3줄 (`run / seconds / generated`) | 표 2 | ✅ |
| 3 | 측정 PC 사양 (CPU, RAM, GPU, vLLM 사용 여부) | III.1 실험 환경 | ✅ |
| 4 | `practice-filter-9b/` 폴더와 9B 출력 3줄 (또는 "9B 미설치"·오류 메시지) | 표 2 | 가능하면 |
| 5 | 판정을 채운 `review_sheet.csv` | 채택군·기각군 환각 비율 | 가능하면 |
| 6 | 생성된 질문 화면 스크린샷 | 그림·포스터 후보 | 선택 |

가져온 뒤에는 이 대화에서 파일 경로를 `@`로 붙이면 된다. 그러면 `docs/paper-revision.md`의 `【측정값】`을 채운다.
