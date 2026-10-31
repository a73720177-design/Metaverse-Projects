"""Measure which expected-question filter rule rejects model candidates (paper experiment 2).

Replays a saved practice session request through PracticeService with a filter
observer attached. Results are not saved as practice sessions. Each candidate is
counted once, under the first rule it failed; the rules run in this order:
format -> evidence_id -> specific_terms -> quantity -> duplicate.

Run inside the backend container:
  python -m scripts.measure_practice_filter --repeats 3 --out /tmp/practice-filter
Aggregate an existing events file anywhere (stdlib only):
  python measure_practice_filter.py --summarize events.jsonl
"""

import argparse
import asyncio
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from time import perf_counter
from uuid import UUID

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

RULES = ["format", "evidence_id", "specific_terms", "quantity", "duplicate"]
RULE_LABELS = {
    "malformed": "구조 오류(JSON 필드)",
    "format": "형식",
    "evidence_id": "근거 ID",
    "specific_terms": "고유 용어",
    "quantity": "수치 불일치",
    "duplicate": "중복",
}


async def run(session_id: UUID | None, repeats: int, model: str | None) -> list[dict]:
    from sqlalchemy import select

    from app import config  # noqa: F401 - load backend/.env
    from app.db.database import get_session_factory
    from app.db.tables import PracticeSessionTable
    from app.dependencies import get_practice_service
    from app.models.practice import ExpectedQuestionRequest
    from app.repositories.practice_repository import InMemoryPracticeRepository

    async with get_session_factory()() as db:
        query = select(PracticeSessionTable)
        if session_id is not None:
            query = query.where(PracticeSessionTable.session_id == session_id)
        row = await db.scalar(query.order_by(PracticeSessionTable.created_at.desc()).limit(1))
    if row is None:
        raise SystemExit("연습 기록이 없습니다. 앱에서 예상 질문을 한 번 생성한 뒤 다시 실행하세요.")
    request = ExpectedQuestionRequest.model_validate(row.payload["request"])
    if model:
        request = request.model_copy(update={"model": model})

    events: list[dict] = []
    service = get_practice_service()
    service.session_repository = InMemoryPracticeRepository()
    for repeat in range(1, repeats + 1):
        def observer(event, repeat=repeat):
            events.append({"run": repeat, "session_id": str(row.session_id),
                           "model": request.model, **event})
        service.filter_observer = observer
        started = perf_counter()
        result = await service.generate_expected_questions(request, row.owner_id)
        elapsed = perf_counter() - started
        print(json.dumps({
            "run": repeat, "model": request.model, "seconds": round(elapsed, 1),
            "generated": {r.persona_name: f"{r.generated_count}/{r.requested_count}" for r in result.results},
        }, ensure_ascii=False), flush=True)
    return events


def summarize(events: list[dict]) -> str:
    candidates = [e for e in events if e["reason"] not in {"generation_error", "surplus"}]
    counts = Counter(e["reason"] for e in candidates)
    total = len(candidates)

    def pct(value: int, base: int) -> str:
        return f"{value / base * 100:.1f}%" if base else "-"

    runs = sorted({e["run"] for e in events})
    lines = [
        f"# 예상 질문 필터 측정 결과 (실행 {len(runs)}회, 모델 {', '.join(sorted({str(e.get('model')) for e in events}))})",
        "",
        "후보 1개는 처음 걸린 규칙 하나에만 집계됨. 규칙 순서: 형식 → 근거 ID → 고유 용어 → 수치 → 중복.",
        "",
        "| 단계 | 후보 수 | 기각 수 | 비율(전체 후보 대비) |",
        "|---|---|---|---|",
    ]
    remaining = total - counts["malformed"]
    if counts["malformed"]:
        lines.append(f"| {RULE_LABELS['malformed']} | {total} | {counts['malformed']} | {pct(counts['malformed'], total)} |")
    for rule in RULES:
        lines.append(f"| {RULE_LABELS[rule]} | {remaining} | {counts[rule]} | {pct(counts[rule], total)} |")
        remaining -= counts[rule]
    lines.append(f"| 최종 채택 | {remaining} | — | {pct(counts[None], total)} |")
    lines += [
        "",
        f"- 모델 생성 실패(요청 단위): {sum(e['reason'] == 'generation_error' for e in events)}회",
        f"- 목표 개수를 채워 평가하지 않은 후보(surplus): {sum(e['reason'] == 'surplus' for e in events)}개 (위 표에서 제외)",
        "",
        "## 페르소나별",
        "",
        "| 페르소나 | 후보 | 채택 | 채택률 | " + " | ".join(RULE_LABELS[r] for r in RULES) + " |",
        "|---|---|---|---|" + "---|" * len(RULES),
    ]
    by_persona: dict[str, list[dict]] = defaultdict(list)
    for event in candidates:
        by_persona[event["persona_name"]].append(event)
    for name, items in sorted(by_persona.items()):
        persona_counts = Counter(e["reason"] for e in items)
        lines.append(
            f"| {name} | {len(items)} | {persona_counts[None]} | {pct(persona_counts[None], len(items))} | "
            + " | ".join(str(persona_counts[r]) for r in RULES) + " |"
        )
    return "\n".join(lines) + "\n"


def write_review_sheet(events: list[dict], path: Path) -> None:
    """CSV for manual labelling: does the question claim something absent from the slides?"""
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["run", "persona", "attempt", "result", "reason", "question",
                         "evidence_ids", "unsupported_content(Y/N)", "note"])
        for event in events:
            if event["reason"] in {"generation_error", "surplus"}:
                continue
            reason = event["reason"]
            writer.writerow([
                event["run"], event["persona_name"], event["attempt"],
                "accepted" if reason is None else "rejected",
                "" if reason is None else RULE_LABELS.get(reason, reason),
                event["question"], json.dumps(event.get("evidence_ids"), ensure_ascii=False), "", "",
            ])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--session-id", type=UUID, help="기준 연습 기록 ID (기본: 가장 최근 기록)")
    parser.add_argument("--repeats", type=int, default=3, help="같은 요청 반복 횟수")
    parser.add_argument("--model", choices=["qwen3:4b", "qwen3.5:9b"], help="기록의 모델 대신 사용할 모델")
    parser.add_argument("--out", type=Path, default=Path("/tmp/practice-filter"), help="결과 폴더")
    parser.add_argument("--summarize", type=Path, help="기존 events.jsonl만 집계")
    args = parser.parse_args()

    if args.summarize:
        events = [json.loads(line) for line in args.summarize.read_text(encoding="utf-8").splitlines() if line.strip()]
        out = args.summarize.parent
    else:
        if args.repeats < 1:
            parser.error("--repeats must be at least 1")
        events = asyncio.run(run(args.session_id, args.repeats, args.model))
        out = args.out
        out.mkdir(parents=True, exist_ok=True)
        with (out / "events.jsonl").open("w", encoding="utf-8") as handle:
            for event in events:
                handle.write(json.dumps(event, ensure_ascii=False) + "\n")

    report = summarize(events)
    (out / "summary.md").write_text(report, encoding="utf-8")
    write_review_sheet(events, out / "review_sheet.csv")
    print(report)
    print(f"저장 위치: {out}/events.jsonl, summary.md, review_sheet.csv")


if __name__ == "__main__":
    main()
