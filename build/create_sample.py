from pathlib import Path
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.colors import HexColor

root = Path(__file__).resolve().parent
out = root / 'payload/examples/sample-presentation.pdf'
pdfmetrics.registerFont(TTFont('Malgun', 'C:/Windows/Fonts/malgun.ttf'))
pdfmetrics.registerFont(TTFont('MalgunBold', 'C:/Windows/Fonts/malgunbd.ttf'))
c = canvas.Canvas(str(out), pagesize=(960, 540))
c.setTitle('캠퍼스 다회용 컵 대여 서비스 - 가상 발표 예시')
c.setAuthor('Metaverse Local Sample')
slides = [
    ('캠퍼스 다회용 컵 대여 서비스', '작은 실험으로 일회용 컵 사용을 줄이는 제안', [
        ('문제', '교내 카페에서 발생하는 일회용 컵 폐기물을 줄이고자 합니다.'),
        ('대상', '교내 카페 2곳과 자발적으로 참여하는 학생 100명입니다.'),
        ('제안', 'QR로 컵을 빌리고 지정된 반납함에 돌려주는 서비스를 실험합니다.'),
    ]),
    ('4주 동안 검증할 운영 계획', '대여 - 반납 - 세척 - 재공급', [
        ('1주 차', '참여자 모집, 이용 안내, 컵 200개와 반납함 3개를 준비합니다.'),
        ('2~3주 차', 'QR 대여를 운영하고 반납률, 분실 수, 일별 이용량을 기록합니다.'),
        ('4주 차', '참여자 만족도와 카페 운영 부담을 조사해 지속 여부를 결정합니다.'),
    ]),
    ('예산과 성공 기준', '숫자는 기능 체험을 위해 만든 가정입니다', [
        ('예산', '총 150만 원: 컵 60만 원, 반납함 30만 원, 세척·운영 60만 원입니다.'),
        ('성공 기준', '반납률 90% 이상, 만족도 5점 중 4점 이상을 목표로 합니다.'),
        ('위험과 보완', '미반납과 위생 문제가 예상됩니다. 알림과 세척 기록으로 대응합니다.'),
    ]),
]
for num, (title, subtitle, rows) in enumerate(slides, 1):
    c.setFillColor(HexColor('#F3F6F9')); c.rect(0, 0, 960, 540, fill=1, stroke=0)
    c.setFillColor(HexColor('#0D766E')); c.rect(0, 514, 960, 26, fill=1, stroke=0)
    c.setFillColor(HexColor('#132A3A')); c.setFont('MalgunBold', 29); c.drawString(56, 445, title)
    c.setFont('Malgun', 16); c.setFillColor(HexColor('#526777')); c.drawString(56, 406, subtitle)
    for i, (label, body) in enumerate(rows):
        y = 320 - i * 89
        c.setFillColor(HexColor('#0D766E')); c.setFont('MalgunBold', 18); c.drawString(56, y, label)
        c.setFillColor(HexColor('#132A3A')); c.setFont('Malgun', 17); c.drawString(56, y - 31, body)
    c.setFont('Malgun', 11); c.setFillColor(HexColor('#526777'))
    c.drawString(56, 34, '가상 예시 자료 | 업로드 후 예산, 일정, 위험 요소에 관해 질문해 보세요.')
    c.drawRightString(904, 34, f'{num} / 3')
    c.showPage()
c.save()
print(out)
