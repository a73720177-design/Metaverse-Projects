"""Repair only the three demo personas from the known failing session."""
import asyncio
import json
import sys
from pathlib import Path
from uuid import UUID
from sqlalchemy import select
from app.db.database import get_session_factory
from app.db.tables import PracticeSessionTable
from app.dependencies import get_practice_service, get_persona_service
from app.models.persona import PersonaUpdateRequest
from app.models.practice import ExpectedQuestionRequest

BACKUP = Path('/tmp/demo-personas-before-repair.json')
IDS = {UUID(x) for x in ['25962006-ca85-4b38-a9bb-5dbec475f334', '6f348c11-5c28-459c-bbc2-d50b9762b8a9', 'de359132-a8c5-45bf-9748-ae4b54ddf855']}

async def main():
    service = get_practice_service()
    personas = get_persona_service()
    if '--backup' in sys.argv:
        async with get_session_factory()() as db:
            rows = (await db.scalars(select(PracticeSessionTable).order_by(PracticeSessionTable.created_at.desc()).limit(20))).all()
            row = next(r for r in rows if {UUID(p) for p in r.payload['request']['persona_ids']} == IDS)
        profiles = [await service.agent_repository.get(pid, row.owner_id) for pid in IDS]
        if any(p is None for p in profiles):
            raise RuntimeError('Target persona missing')
        BACKUP.write_text(json.dumps({'owner': str(row.owner_id), 'request': row.payload['request'], 'personas': [p.model_dump(mode='json') for p in profiles]}, ensure_ascii=False, indent=2), encoding='utf-8')
        print('Backed up exactly 3 demo personas', flush=True)
        return
    saved = json.loads(BACKUP.read_text(encoding='utf-8'))
    owner = UUID(saved['owner'])
    request = ExpectedQuestionRequest.model_validate(saved['request'])
    if set(request.persona_ids) != IDS:
        raise RuntimeError('Unexpected repair scope')
    for p in ([] if '--questions-only' in sys.argv else saved['personas']):
        updated = await personas.update(UUID(p['agent_id']), PersonaUpdateRequest(
            name=p['name'], description=p['description'], document_ids=p['document_ids'], model=request.model), owner)
        print(json.dumps({'name': updated.name, 'expertise': len(updated.expertise), 'criteria': len(updated.evaluation_style), 'warnings': updated.warnings}, ensure_ascii=False), flush=True)
    result = await service.generate_expected_questions(request, owner)
    report = {'session_id': str(result.session_id), 'results': [{'name': r.persona_name, 'count': r.generated_count, 'warnings': r.warnings} for r in result.results]}
    Path('/tmp/demo-practice-repair-result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False), flush=True)

asyncio.run(main())
