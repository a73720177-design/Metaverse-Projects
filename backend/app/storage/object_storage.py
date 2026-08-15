from pathlib import Path
from typing import Protocol


class ObjectStorage(Protocol):
    bucket: str

    async def upload(
        self, source: Path, object_key: str, content_type: str | None = None
    ) -> None: ...
