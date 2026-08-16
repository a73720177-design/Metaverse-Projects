import asyncio
import os
from pathlib import Path

from minio import Minio


class MinioStorage:
    def __init__(self) -> None:
        self.bucket = os.getenv("MINIO_BUCKET", "documents")
        endpoint = self._required("MINIO_ENDPOINT")
        access_key = self._required("MINIO_ACCESS_KEY")
        secret_key = self._required("MINIO_SECRET_KEY")
        self.client = Minio(
            endpoint=endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=os.getenv("MINIO_SECURE", "false").lower() == "true",
        )

    @staticmethod
    def _required(name: str) -> str:
        value = os.getenv(name, "").strip()
        if not value:
            raise RuntimeError(f"OBJECT_STORAGE_MODE=minio requires {name}.")
        return value

    def _upload(self, source: Path, object_key: str, content_type: str | None) -> None:
        if not self.client.bucket_exists(self.bucket):
            self.client.make_bucket(self.bucket)
        self.client.fput_object(
            self.bucket,
            object_key,
            str(source),
            content_type=content_type or "application/octet-stream",
        )

    async def upload(
        self, source: Path, object_key: str, content_type: str | None = None
    ) -> None:
        await asyncio.to_thread(self._upload, source, object_key, content_type)

    async def delete(self, object_key: str) -> None:
        await asyncio.to_thread(self.client.remove_object, self.bucket, object_key)
