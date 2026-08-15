import asyncio
import os
from pathlib import Path

from minio import Minio


class MinioStorage:
    def __init__(self) -> None:
        self.bucket = os.getenv("MINIO_BUCKET", "documents")
        self.client = Minio(
            endpoint=os.getenv("MINIO_ENDPOINT", "localhost:9000"),
            access_key=os.getenv("MINIO_ACCESS_KEY", "minioadmin"),
            secret_key=os.getenv("MINIO_SECRET_KEY", "minioadmin"),
            secure=os.getenv("MINIO_SECURE", "false").lower() == "true",
        )

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
