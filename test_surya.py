import os
from PIL import Image
from surya.detection import DetectionPredictor

def main():
    print("Surya 텍스트 감지 모델을 불러오는 중입니다...")

    # 1. 감지 예측 모델 객체 생성
    det_predictor = DetectionPredictor()
    print("✅ 모델 로드 완료!\n")

    # 2. 폴더 내에서 자동으로 이미지 파일 찾기
    valid_extensions = ('.png', '.jpg', '.jpeg')
    image_path = None

    # 현재 디렉토리('.')의 모든 파일을 검색
    for file in os.listdir('.'):
        # 파일 확장자가 이미지 형태인지 확인
        if file.lower().endswith(valid_extensions):
            image_path = file
            break  # 첫 번째로 찾은 이미지를 선택하고 검색 종료

    # 이미지를 아예 찾지 못한 경우의 예외 처리
    if not image_path:
        print("⚠️ 현재 폴더에 이미지 파일(.png, .jpg 등)이 없습니다. 이미지를 폴더 안에 하나 넣어주세요.")
        return

    # 3. 이미지 불러오기 및 텍스트 감지 실행
    print(f"🔍 자동으로 '{image_path}' 파일을 찾았습니다! 분석을 시작합니다...")
    image = Image.open(image_path)

    predictions = det_predictor([image])

    # 4. 결과 출력
    print("\n✅ 분석 완료! 감지된 텍스트 영역 정보 (첫 5개):")
    result = predictions[0]

    bboxes = result.bboxes if hasattr(result, 'bboxes') else result.get('bboxes', [])

    for idx, item in enumerate(bboxes[:5]):
        polygon = item.polygon if hasattr(item, 'polygon') else item.get('polygon')
        print(f"영역 {idx+1} - 좌표: {polygon}")

if __name__ == "__main__":
    main()