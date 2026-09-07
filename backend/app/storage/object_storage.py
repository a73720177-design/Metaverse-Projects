from pathlib import Path
from typing import Protocol


class ObjectStorageError(RuntimeError):
    pass


class ObjectStorage(Protocol):
    bucket: str

    async def upload(
        self, source: Path, object_key: str, content_type: str | None = None
    ) -> None: ...

    async def delete(self, object_key: str) -> None: ...
