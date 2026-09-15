# 로컬 VLM으로 발표자료 분석하기

## 구현한 흐름

`PPTX/PDF 업로드 → 기존 텍스트 추출 → 페이지 PNG 렌더링 → 로컬 VLM → 텍스트와 시각 분석 저장 → 예상 질문·리뷰·요약·RAG`

- PPTX는 LibreOffice로 전체 슬라이드를 PDF로 변환합니다. 삽입 사진뿐 아니라 표, 차트, 도형, 화살표와 배치를 함께 읽습니다. PDF는 PyMuPDF로 페이지 전체를 렌더링하므로 스캔 문서도 처리합니다.
- PPTX 기본 텍스트 파서도 표와 그룹 안의 텍스트를 읽습니다.
- 원본 텍스트를 유지하고 각 페이지 뒤에 `[시각 분석 · 페이지 N · AI 해석, 원본 확인 필요]`를 붙입니다. 비어 있는 페이지도 분석 대상입니다.
- 결과는 기존 `sections`, `full_text`에 저장되므로 메모리/PostgreSQL 저장소, 기존 벡터 인덱싱과 질문·리뷰 경로가 같은 내용을 사용합니다. DB migration은 필요하지 않습니다.
- 중간 PNG/PDF는 임시 디렉터리에서 처리한 뒤 지웁니다. 기존 원본 파일 저장 방식은 유지합니다.
- VLM은 관찰 내용과 판독 불가 항목을 추출합니다. 예상 질문과 피드백은 기존 로컬 LLM이 페르소나를 적용해 생성합니다. 프롬프트는 VLM 해석을 확정 사실이나 원문 인용으로 취급하지 않도록 안내합니다. 모델 오독 자체를 완전히 막을 수는 없습니다.

## 모델 선택

기본값은 **`qwen3-vl:4b-instruct`**입니다. 기존 Ollama와 같은 런타임을 사용하고, 별도 Python 모델 서버나 CUDA 패키지 없이 이미지 입력 API로 호출할 수 있기 때문입니다. 한국어 발표자료의 실제 판독 품질은 사용자 자료로 추가 평가해야 합니다.

| 선택 | 용도 | 유의점 |
| --- | --- | --- |
| Qwen3-VL 2B | 자원이 적은 장비에서 시험 | 작은 글씨와 복잡한 도표는 원본과 대조 필요 |
| Qwen3-VL 4B Instruct | 기본 구성 | 공식 Ollama 배포 약 3.3GB. 실행 메모리는 모델 파일보다 큼 |
| Qwen3-VL 8B | 여유 있는 장비에서 품질 비교 | 더 많은 메모리와 처리 시간 필요. 이 저장소에서 성능 비교는 미실시 |

OCR 텍스트 추출만으로는 차트의 축, 연결선, 범례 및 배치를 복원하기 어렵기 때문에 전체 페이지 VLM 방식을 선택했습니다. 별도 OCR 엔진은 추가하지 않았습니다. 정밀 표 셀 복원이나 매우 작은 글씨가 핵심인 자료에는 추후 부분 확대/OCR 병합이 필요할 수 있습니다.

## 설치 및 활성화

Ollama와 LibreOffice가 백엔드와 같은 장비에 있어야 합니다. 기존 LLM은 기존 설정을 유지합니다.

```bash
# Ollama 0.12.7 이상 필요. 지원되는 최신 버전 권장.
ollama pull qwen3-vl:4b-instruct
# Ollama가 실행 중이지 않을 때만 실행
ollama serve
```

LibreOffice 설치:

```bash
# macOS
brew install --cask libreoffice
# Ubuntu/Debian
sudo apt-get install libreoffice-impress fonts-noto-cjk
```

`backend/.env`에 설정하고 백엔드를 재시작합니다.

```dotenv
DOCUMENT_VISION_MODE=ollama
VLM_BASE_URL=http://127.0.0.1:11434
VLM_MODEL=qwen3-vl:4b-instruct
LIBREOFFICE_BINARY=soffice
VLM_MAX_PAGES=40
VLM_IMAGE_MAX_EDGE=1600
VLM_PAGE_TIMEOUT_SECONDS=120
VLM_DOCUMENT_TIMEOUT_SECONDS=600
```

macOS에서 `soffice`를 찾지 못하면 `LIBREOFFICE_BINARY=/Applications/LibreOffice.app/Contents/MacOS/soffice`로 지정합니다. 한글 글꼴을 설치해야 슬라이드 렌더링에서 글꼴 대체/글자 누락을 줄일 수 있습니다.

코드 기본값과 `.env.example`은 `DOCUMENT_VISION_MODE=off`로 두었습니다. 모델 설치가 없는 기존 개발 환경의 텍스트 파싱을 유지하기 위한 설정입니다. `ollama`로 바꿔야 이미지 분석이 실행됩니다. 기존 업로드에는 자동 소급 적용되지 않으므로 원본을 다시 업로드해 새 문서를 연결해야 합니다.

## 동작 제한과 실패 처리

- 로컬 전용: HTTP 루프백 주소만 허용하고, cloud 이름의 모델·환경 프록시·리다이렉트는 사용하지 않습니다.
- 한 백엔드 프로세스에서 한 문서씩 분석합니다. 다른 분석이 진행 중이면 503을 반환합니다. 여러 worker를 사용하면 worker별 제한이므로 단일 GPU 환경에서는 한 worker를 권장합니다.
- 기본 최대 40페이지, 이미지 긴 변 1600px(설정 상한 2400px), 페이지 요청 제한 120초입니다. 문서 처리 예산은 600초이며 각 페이지 호출 전후에 확인합니다. HTTP 제한은 연결/읽기 단계별 제한이므로 엄격한 전체 작업 취소 타이머는 아닙니다.
- LibreOffice 변환 제한은 최대 60초입니다. 프런트 업로드 대기는 15분입니다. 별도 reverse proxy가 있다면 업로드 응답 대기도 맞춰야 합니다.
- 메모리를 다른 로컬 모델에 돌려주기 위해 페이지 요청의 `keep_alive=0`을 사용합니다. 페이지마다 모델 재로딩이 발생할 수 있어 긴 자료는 느립니다. 제한에 걸리면 파일을 나눠 업로드하세요.
- VLM 오류/모델 없음/렌더링 실패는 503, 손상 파일/페이지 수 초과는 400을 반환합니다. 이미지 분석이 켜져 있으면 실패한 문서를 텍스트만 있는 성공 결과로 저장하지 않습니다.
- 업로드는 동기 응답 방식입니다. 브라우저 요청 취소가 이미 실행 중인 서버 추론을 즉시 중단시키지는 않습니다. 작업 큐와 중간 결과 재개는 현재 구현 범위에 포함되지 않습니다.
- DOCX는 기존 텍스트 파싱을 사용합니다. PPTX 애니메이션·동영상의 시간 흐름은 정적 렌더링에 포함되지 않습니다.

## 확인 방법

1. 이미지로만 된 슬라이드와 표/차트 슬라이드를 포함한 PPTX를 업로드합니다.
2. `/documents/{document_id}` 응답의 각 `sections[].text`에서 시각 분석과 원본 페이지 번호를 확인합니다.
3. 기존 발표 연습에서 그 문서를 연결하고 차트의 단위/추세에 대한 예상 질문과 피드백을 생성합니다.
4. 수치, 범례, 한글 판독을 실제 슬라이드와 대조합니다.

자동 테스트:

```bash
cd backend
.venv/bin/python -m pytest tests/test_visual_parsing.py tests/test_document_service.py -q
```

테스트는 실제 PyMuPDF 이미지 렌더링, PPTX 표/그룹 추출, 이미지 API 계약, 페이지 번호와 검색 연결, 오류 시 미저장/임시파일 정리, 로컬 전용 설정을 검증합니다. LibreOffice 프로세스와 Ollama 추론은 테스트 대역을 사용합니다. 구현 세션에서는 로컬 서비스 접근 권한이 허용되지 않아 실제 모델 추론 및 실제 LibreOffice 변환은 검증하지 못했습니다.

## 공식 참고 자료

- [Qwen3-VL 4B Instruct 모델·크기·Ollama 최소 버전](https://ollama.com/library/qwen3-vl:4b-instruct)
- [Qwen3-VL 모델 크기 목록](https://ollama.com/library/qwen3-vl/tags)
- [Ollama Vision API: base64 images 입력](https://docs.ollama.com/capabilities/vision)
- [LibreOffice headless 및 PDF 변환 옵션](https://help.libreoffice.org/latest/en-US/text/shared/guide/start_parameters.html)
- [vLLM 멀티모달 API](https://docs.vllm.ai/en/stable/features/multimodal_inputs/): 별도 GPU 서버로 확장할 때의 대안이며 현재 어댑터는 Ollama 전용입니다.
