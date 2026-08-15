import os
import torch
from transformers import AutoModel, AutoTokenizer

def main():
    print("GOT-OCR 2.0 모델을 불러오는 중입니다...")
    print("(주의: 첫 실행 시 약 8GB 용량의 모델 파일을 다운로드하므로 시간이 다소 걸립니다.)")

    # 1. 토크나이저 및 모델 로드
    # trust_remote_code=True 옵션이 반드시 필요합니다.
    tokenizer = AutoTokenizer.from_pretrained('stepfun-ai/GOT-OCR2_0', trust_remote_code=True)

    model = AutoModel.from_pretrained(
        'stepfun-ai/GOT-OCR2_0',
        trust_remote_code=True,
        low_cpu_mem_usage=True,
        device_map='cuda', # GPU 메모리에 모델을 할당합니다.
        use_safetensors=True
    )
    model = model.eval()
    print("✅ 모델 로드 완료!\n")

    # 2. 자동 이미지 탐색 (Surya 테스트와 동일)
    valid_extensions = ('.png', '.jpg', '.jpeg')
    image_path = None

    for file in os.listdir('.'):
        if file.lower().endswith(valid_extensions):
            image_path = file
            break

    if not image_path:
        print("⚠️ 현재 폴더에 이미지 파일이 없습니다.")
        return

    print(f"🔍 '{image_path}' 분석을 시작합니다. (표/수식을 마크다운으로 변환 중...)")

    # 3. 마크다운 포맷팅 기반 OCR 실행
    # ocr_type='format'으로 지정하면 텍스트뿐만 아니라 표의 격자 구조나 복잡한 수식까지 마크다운으로 출력해줍니다.
    try:
        res = model.chat(tokenizer, image_path, ocr_type='format')
        print("\n✅ 분석 완료! 추출된 마크다운 결과:\n")
        print("=" * 50)
        print(res)
        print("=" * 50)
    except Exception as e:
        print(f"오류가 발생했습니다: {e}")

if __name__ == "__main__":
    main()