import asyncio
import os
import signal
import sys
import json
from app.integrations.vision import VisionUnavailableError
from app.config import BACKEND_ROOT
from app.models.document import DocumentParseResponse


async def parse_in_process(path, filename):
    timeout = int(os.getenv("PARSER_TIMEOUT_SECONDS", "650" if os.getenv("DOCUMENT_VISION_MODE") == "ollama" else "120"))
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "app.parsers.worker", str(path), filename,
        cwd=BACKEND_ROOT, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        start_new_session=os.name == "posix",
    )
    try:
        output, _ = await asyncio.wait_for(process.communicate(), timeout)
        if process.returncode:
            raise ValueError("문서 분석 프로세스가 자원 제한 또는 오류로 종료되었습니다.")
        data = json.loads(output)
        if data.get("code") == "vision_unavailable":
            raise VisionUnavailableError(data["error"])
        if "error" in data:
            raise ValueError(data["error"])
        return DocumentParseResponse.model_validate(data)
    except asyncio.TimeoutError as exc:
        raise ValueError("문서 분석 시간 제한을 초과했습니다.") from exc
    finally:
        if process.returncode is None:
            try:
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
            except ProcessLookupError:
                pass
            await process.wait()
