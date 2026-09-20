from app.services.content_budget import assess_content


def test_empty_and_heading_only_material_cannot_fund_questions():
    assert assess_content(["", "목차\n소개\n감사합니다"]).output_limit == 0


def test_duplicate_files_and_repeated_sentences_do_not_inflate_budget():
    sentence = "사용자 실험에서 전환율 개선 효과를 확인하고 측정 방법을 기록했습니다."
    one = assess_content([sentence])
    assert one.output_limit == 1
    assert assess_content([sentence] * 20) == one
    assert assess_content([sentence * 100]) == one


def test_distinct_supported_content_increases_budget():
    short = assess_content(["사용자 실험에서 전환율 개선 효과를 확인했습니다."])
    rich = assess_content([
        "사용자 실험에서 전환율 개선 효과와 측정 방법을 확인했습니다.",
        "운영 비용은 서버 임대료와 인건비를 포함하여 월별로 계산합니다.",
        "보안 정책은 접근 권한을 제한하고 감사 기록으로 침입을 탐지합니다.",
        "시장 조사는 고객 면담을 통해 경쟁 제품의 가격 차이를 비교합니다.",
    ])
    assert short.output_limit < rich.output_limit <= 4


def test_rich_content_reaches_eight_and_reports_saturation():
    # Distinct vocabulary rather than repeating padding to simulate volume.
    texts = [' '.join(f'항목{i}내용{j}' for j in range(60)) for i in range(10)]
    result = assess_content(texts)
    assert result.output_limit == 8 and result.saturated


def test_expected_question_budget_can_reach_ten_without_changing_default_budget():
    texts = [' '.join(f'질문근거{i}항목{j}' for j in range(60)) for i in range(12)]
    result = assess_content(texts, max_output=10)
    assert result.output_limit == 10
    assert result.saturated
    assert assess_content(texts).output_limit == 8
