"""Render complete slides/pages, preserving charts, vectors and layout."""
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
from time import monotonic
from threading import BoundedSemaphore

import fitz

from app.config import _get_positive_int
from app.integrations.vision import OllamaVisionClient, VisionUnavailableError


_VISION_SLOT = BoundedSemaphore(1)


def enrich_visual_pages(path: Path, parsed: list[tuple[int, str]]) -> list[tuple[int, str]]:
    # One document per backend process: avoid loading many images/model jobs at once.
    if not _VISION_SLOT.acquire(blocking=False):
        raise VisionUnavailableError("다른 문서의 이미지 분석이 진행 중입니다. 완료 후 다시 업로드하세요.")
    try:
        return _enrich_visual_pages(path, parsed)
    finally:
        _VISION_SLOT.release()


def _enrich_visual_pages(path: Path, parsed: list[tuple[int, str]]) -> list[tuple[int, str]]:
    max_pages = _get_positive_int("VLM_MAX_PAGES", 40)
    max_edge = min(_get_positive_int("VLM_IMAGE_MAX_EDGE", 1600), 2400)
    deadline = monotonic() + _get_positive_int("VLM_DOCUMENT_TIMEOUT_SECONDS", 600)
    page_timeout = _get_positive_int("VLM_PAGE_TIMEOUT_SECONDS", 120)
    client = OllamaVisionClient()
    with client.document_session(), TemporaryDirectory(prefix="document-vision-") as directory:
        work = Path(directory)
        pdf_path = path
        if path.suffix.lower() == ".pptx":
            if len(parsed) > max_pages:
                raise ValueError(f"이미지 분석은 최대 {max_pages}페이지까지 지원합니다. 파일을 나눠주세요.")
            executable = shutil.which(os.getenv("LIBREOFFICE_BINARY", "soffice"))
            if executable is None:
                raise VisionUnavailableError("PPTX 이미지 분석에 LibreOffice가 필요합니다. 설치 후 다시 업로드하세요.")
            # A separate profile prevents concurrent uploads/desktop sessions from
            # swallowing conversions. A fixed input name prevents option injection.
            source = work / "source.pptx"
            shutil.copyfile(path, source)
            try:
                subprocess.run([
                    executable, f"-env:UserInstallation={(work / 'profile').as_uri()}",
                    "--headless", "--convert-to", "pdf:impress_pdf_Export", "--outdir",
                    str(work), str(source),
                ], check=True, timeout=min(60, max(1, deadline - monotonic())),
                    capture_output=True)
            except (OSError, subprocess.SubprocessError) as exc:
                raise VisionUnavailableError("LibreOffice 슬라이드 렌더링에 실패했습니다.") from exc
            pdf_path = work / "source.pdf"
            if not pdf_path.is_file():
                raise VisionUnavailableError("LibreOffice가 슬라이드 PDF를 생성하지 못했습니다.")
        try:
            document = fitz.open(pdf_path)
        except (RuntimeError, ValueError) as exc:
            raise ValueError("이미지 분석을 위한 PDF를 읽을 수 없습니다.") from exc
        with document:
            if not 0 < len(document) <= max_pages:
                raise ValueError(f"이미지 분석은 1~{max_pages}페이지 문서를 지원합니다. 파일을 나눠주세요.")
            if path.suffix.lower() == ".pptx" and len(document) != len(parsed):
                raise ValueError("렌더링된 페이지 수가 슬라이드 수와 다릅니다. PDF로 내보내 다시 업로드하세요.")
            texts = dict(parsed)
            result = []
            for index, page in enumerate(document, 1):
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise VisionUnavailableError("문서 이미지 분석 제한 시간을 초과했습니다. 파일을 나눠주세요.")
                edge = max(page.rect.width, page.rect.height)
                if edge <= 0:
                    raise ValueError("페이지 크기가 올바르지 않습니다.")
                scale = max_edge / edge
                png = page.get_pixmap(matrix=fitz.Matrix(scale, scale),
                                      colorspace=fitz.csRGB, alpha=False).tobytes("png")
                text = texts.get(index, "").strip()
                analysis = client.describe(png, text, index, min(page_timeout, remaining))
                if monotonic() > deadline:
                    raise VisionUnavailableError("문서 이미지 분석 제한 시간을 초과했습니다. 파일을 나눠주세요.")
                visual = f"[시각 분석 · 페이지 {index} · AI 해석, 원본 확인 필요]\n{analysis}"
                result.append((index, f"{text}\n\n{visual}".strip()))
            return result
