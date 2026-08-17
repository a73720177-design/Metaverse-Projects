import asyncio
import os
import shutil
from pathlib import Path

from app.storage.object_storage import ObjectStorageError


class LocalStorage:
    """Development object storage backed by a directory on this machine."""

    def __init__(self) -> None:
        default_root = Path(__file__).resolve().parents[2] / "uploads" / "objects"
        self.root = Path(os.getenv("LOCAL_STORAGE_DIR", str(default_root))).resolve()
        self.bucket = "local"

    def _target(self, object_key: str) -> Path:
        target = (self.root / object_key).resolve()
        if self.root != target and self.root not in target.parents:
            raise ValueError("Invalid object key.")
        return target

    async def upload(
        self, source: Path, object_key: str, content_type: str | None = None
    ) -> None:
        target = self._target(object_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            await asyncio.to_thread(shutil.copy2, source, target)
        except OSError as exc:
            raise ObjectStorageError("Local upload failed.") from exc

    async def delete(self, object_key: str) -> None:
        try:
            await asyncio.to_thread(self._target(object_key).unlink, missing_ok=True)
        except OSError as exc:
            raise ObjectStorageError("Local delete failed.") from exc
