import asyncio
import json
import os
import signal
import subprocess
import sys
from app.integrations.vision import VisionUnavailableError
from app.config import BACKEND_ROOT
from app.models.document import DocumentParseResponse


async def _terminate_process_tree(process) -> None:
    """Terminate the parser and any converter processes it spawned."""
    if process.returncode is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            killer = await asyncio.create_subprocess_exec(
                "taskkill",
                "/PID",
                str(process.pid),
                "/T",
                "/F",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await killer.wait()
            if process.returncode is None:
                process.kill()
    except (FileNotFoundError, ProcessLookupError):
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
    await process.wait()


async def parse_in_process(path, filename):
    timeout = int(os.getenv(
        "PARSER_TIMEOUT_SECONDS",
        "650" if os.getenv("DOCUMENT_VISION_MODE") in {"auto", "ollama"} else "120",
    ))
    worker_env = os.environ.copy()
    worker_env.update({"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
    process_options = (
        {"start_new_session": True}
        if os.name == "posix"
        else {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    )
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "app.parsers.worker", str(path), filename,
        cwd=BACKEND_ROOT, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        env=worker_env,
        **process_options,
    )
    try:
        output, _ = await asyncio.wait_for(process.communicate(), timeout)
        if process.returncode:
            raise ValueError("문서 분석 프로세스가 자원 제한 또는 오류로 종료되었습니다.")
        try:
            data = json.loads(output.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("문서 분석 결과를 읽을 수 없습니다.") from exc
        if data.get("code") == "vision_unavailable":
            raise VisionUnavailableError(data["error"])
        if "error" in data:
            raise ValueError(data["error"])
        return DocumentParseResponse.model_validate(data)
    except asyncio.TimeoutError as exc:
        raise ValueError("문서 분석 시간 제한을 초과했습니다.") from exc
    finally:
        if process.returncode is None:
            await _terminate_process_tree(process)
