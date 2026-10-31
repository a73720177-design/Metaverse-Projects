# Windows의 Claude에게 맡길 측정 작업

Windows PC의 Claude Code에 측정을 통째로 맡기고, **결과 폴더 하나(`paper-results.zip`)만** Mac의 이 채팅으로 가져오기 위한 문서다.

---

## A. 사람이 먼저 할 일 (10~20분)

Claude가 할 수 없거나, 사람이 하는 편이 안전한 일들이다.

- [ ] **A-1. 저장소 받기:** `claude/academic-paper-prompt-d1ed05` 브랜치를 clone 또는 pull한다.
  - 이 브랜치에 측정 코드 2개, 최신 `Metaverse-Setup.exe`, 이 문서가 들어 있어야 한다.
  - Mac에서 먼저 커밋·push해야 한다.
- [ ] **A-2. 최신 EXE로 설치:** 저장소 루트의 `Metaverse-Setup.exe`를 실행한다. `최종.zip`의 EXE는 구버전이므로 쓰지 않는다.
  - 모델 선택에서 **3번(둘 다 설치)**을 고른다.
  - 이미 구버전으로 설치되어 있으면 'Metaverse 서버 종료' 후 새 EXE를 실행한다.
  - 설치에는 UAC 창이나 재부팅이 끼어 있으므로 사람이 직접 한다.
- [ ] **A-3. 앱에서 시연 기록 만들기:** 로그인 → 아래 조건으로 예상 질문을 1회 생성한다.
  - 발표자료: `시연_예시자료/01_시연용_발표자료_캠퍼스_분리배출.pptx`, `02_발표대본_캠퍼스_분리배출.pdf`
  - 페르소나 3명과 각자의 참고자료:
    - 기술검토자 ← `03_페르소나_소스_기술검토자.pdf`
    - 운영예산 ← `04_페르소나_소스_운영예산.pdf`
    - 학생경험 ← `05_페르소나_소스_학생경험.pdf`
  - 페르소나당 질문 **5개**, 모델 **qwen3:4b**
  - 생성이 끝나면 **화면 스크린샷 1장**을 저장한다. 세 패널이 모두 보이게 찍고, 분석 범위 표시(예: 4/12)도 보이게 한다.
  - 생성 버튼부터 질문이 다 뜰 때까지의 시간을 대략 재 둔다. 예: 약 90초.
- [ ] **A-4. Claude Code 실행:** 저장소 루트 폴더에서 연다.
  - 권한은 넓게 줘도 되지만, 아래 프롬프트의 "금지" 목록은 그대로 둔다.
  - **Docker 볼륨 삭제는 시연 기록과 모델을 모두 지운다.**

## B. Claude에게 붙여 넣을 프롬프트

아래 블록 전체를 복사해서 Windows의 Claude Code에 붙여 넣는다. `【 】` 두 칸은 A-3에서 잰 값으로 바꾼다.

```text
이 저장소는 발표 준비 지원 앱이고, 학회 논문용 측정을 하려고 한다. 앱은 이미 최신 Metaverse-Setup.exe로 설치되어 Docker에서 실행 중이고, 앱 화면에서 예상 질문을 한 번 생성해 두었다. PowerShell로 아래 작업을 끝까지 수행하고, 결과를 저장소 루트의 paper-results 폴더에 모은 뒤 paper-results.zip으로 압축해줘.

[금지]
- docker volume rm, docker compose down -v, docker system prune 등 볼륨·이미지를 지우는 명령
- 앱 재설치, Metaverse-Setup.exe 실행, WSL 해제·재설치
- 저장소 파일 수정, git commit/push (paper-results 폴더 생성만 허용)
- 컨테이너 재시작은 꼭 필요할 때만 하고, 했다면 결과 보고서에 적기
막히면 우회하지 말고 멈춘 뒤 상황과 오류 전문을 보고해줘.

[1. 환경 확인] 결과를 paper-results/env.txt에 저장
- docker ps --format "{{.Names}}  {{.Image}}  {{.Status}}" 결과. backend, ollama, vllm 컨테이너 이름을 찾고, vllm 컨테이너가 있으면 GPU(vLLM) 모드다.
- vllm 컨테이너가 있으면 그 컨테이너가 서빙 중인 실제 모델 이름(컨테이너 실행 인자나 /v1/models 응답)
- docker exec <ollama> ollama list
- CPU 이름·코어 수, RAM(GB), GPU 이름·VRAM(nvidia-smi --query-gpu=name,memory.total --format=csv; 없으면 "NVIDIA GPU 없음"), Windows 버전
- Get-FileHash .\Metaverse-Setup.exe -Algorithm SHA256 결과와 SHA256.txt 내용 비교

[2. 설치 버전 확인] 반드시 파일을 복사하기 전에 할 것
- docker exec <backend> python -c "s=open('/app/app/services/practice_service.py',encoding='utf-8').read(); print('range(6 if count' in s)"
- False면 구버전이 설치된 것이므로 여기서 멈추고 보고해줘. 측정 코드를 덮어쓰면 안 된다.

[3. 측정 코드 넣기]
- docker cp build/payload/backend/app/services/practice_service.py <backend>:/app/app/services/practice_service.py
- docker cp build/payload/backend/scripts/measure_practice_filter.py <backend>:/app/scripts/measure_practice_filter.py
- 'filter_observer'가 컨테이너 파일에 들어갔는지 True로 확인

[4. 측정] 각 명령의 화면 출력 전체를 paper-results/run-log.txt에 이어서 저장
- 예열: docker exec <backend> python -m scripts.measure_practice_filter --model qwen3:4b --repeats 1 --out /tmp/warmup
- 4B: docker exec <backend> python -m scripts.measure_practice_filter --model qwen3:4b --repeats 3 --out /tmp/practice-filter-4b
- ollama list에 qwen3.5:9b가 있으면 9B도 예열 1회 후 --repeats 3, --out /tmp/practice-filter-9b
- 9B가 오류나면 오류 전문을 저장하고 4B 결과로 계속 진행
- 각 명령은 수십 분 걸릴 수 있으니 타임아웃을 넉넉히 주고, 오래 걸려도 중단하지 마.
- 측정 중 nvidia-smi를 한 번 실행해 GPU 사용 여부를 run-log.txt에 남겨줘.

[5. 결과 꺼내기]
- docker cp <backend>:/tmp/practice-filter-4b paper-results/practice-filter-4b (9B도 있으면 같은 방식)
- 각 폴더에 events.jsonl, summary.md, review_sheet.csv가 있는지 확인

[6. 질문 판정 초안] review_sheet.csv는 수정하지 말고, 복사본 paper-results/review_sheet_claude.csv를 만들어
- 각 질문이 발표자료(시연_예시자료/01 pptx, 02 pdf)에 없는 사실·수치·주장을 전제로 하는지 판단해 unsupported_content(Y/N)를 채우고, note에 근거(자료의 어느 문장인지 또는 무엇이 없는지)를 짧게 적어줘.
- "~는 어떻게 검증했나요?"처럼 자료 내용을 묻기만 하는 질문은 N이다. 애매하면 N으로 두지 말고 note에 "애매"라고 적어.
- 이것은 사람이 검토할 초안이라는 점을 보고서에 명시해줘.

[7. 보고서] paper-results/RESULTS.md
- 측정 환경(CPU/RAM/GPU/Windows/vLLM 여부/실제 서빙 모델)
- 모델별 회차 시간(seconds)과 페르소나별 generated
- summary.md 표 그대로
- 채택군·기각군 각각의 Y 비율(판정 초안 기준)
- 사람이 앱에서 측정한 값: 생성 소요 약 【A-3 시간】초, 분석 범위 【A-3 분석 구간 예: 4/12】
- 실행 중 생긴 오류, 재시도, 컨테이너 재시작 여부

[8. 압축] paper-results 폴더를 paper-results.zip으로 압축하고, 파일 목록과 크기를 보여줘.
```

## C. 끝나면

- [ ] **C-1.** `paper-results` 폴더에 A-3의 **스크린샷**을 직접 넣고 다시 압축한다. Claude가 압축한 뒤라면 zip을 다시 만든다.
- [ ] **C-2. (가능하면) 판정 검토:** `review_sheet_claude.csv`에서 "애매" 또는 Y인 행만 사람이 확인하고 고친다. 고쳤다면 파일 이름에 `_checked`를 붙인다.
- [ ] **C-3.** `paper-results.zip`을 Mac으로 옮긴다(USB, 메일, 드라이브 등).
- [ ] **C-4.** 이 채팅에 `@paper-results.zip` 경로를 붙이고 "결과 가져왔어"라고 하면 된다.

## 가져올 결과물 (`paper-results.zip` 안)

| 파일 | 쓰는 곳 | 필수 |
|---|---|---|
| `RESULTS.md` | 전체 요약, 보강안 【시연 확인】 칸 | ✅ |
| `env.txt` | 실험 환경, 실제 서빙 모델 | ✅ |
| `run-log.txt` | 회차별 시간, 오류 확인 | ✅ |
| `practice-filter-4b/` (events.jsonl, summary.md, review_sheet.csv) | 필터 단계별 기각률 표 | ✅ |
| `review_sheet_claude.csv` (또는 `_checked`) | 근거 없는 질문 비율 | 가능하면 |
| `practice-filter-9b/` 또는 9B 오류 기록 | 모델 비교 | 가능하면 |
| 시연 화면 스크린샷 | 그림 2, 표 2, 발표 PPT | ✅ |

## 문제가 생기면

| 증상 | 조치 |
|---|---|
| 2단계에서 False | 구버전 설치. A-2를 다시 하고(서버 종료 → 최신 EXE) A-3부터 반복 |
| `연습 기록이 없습니다` | A-3을 안 했거나 다른 계정·DB. 앱에서 질문 생성을 1회 다시 한다 |
| Claude가 금지 명령을 하려 함 | 거부하고 프롬프트의 [금지] 부분을 다시 보여 준다 |
| 측정이 1시간 넘게 끝나지 않음 | `docker logs <backend> --tail 50`으로 진행 여부를 본다. 멈췄으면 `--repeats 1`로 줄여 다시 실행 |
