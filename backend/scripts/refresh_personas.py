"""Regenerate active personas from their descriptions and linked source documents."""

import argparse
import asyncio
import sys
from pathlib import Path
from uuid import UUID

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app import config  # noqa: E402,F401 - load backend/.env
from app.dependencies import get_persona_service  # noqa: E402
from app.models.persona import PersonaUpdateRequest  # noqa: E402


async def refresh(owner_id: UUID) -> int:
    service = get_persona_service()
    personas = await service.list_active(owner_id)
    refreshed = 0
    for persona in personas:
        request = PersonaUpdateRequest(
            name=persona.name,
            description=persona.description,
            gender=persona.gender,
            age=persona.age,
            document_ids=persona.document_ids,
        )
        updated = await service.update(persona.agent_id, request, owner_id)
        refreshed += 1
        print(
            f"{updated.agent_id}: role={updated.role!r}, "
            f"expertise={len(updated.expertise)}, style={len(updated.evaluation_style)}",
            flush=True,
        )
    return refreshed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner-id", type=UUID, required=True)
    args = parser.parse_args()
    total = asyncio.run(refresh(args.owner_id))
    print(f"Completed: {total} personas refreshed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
