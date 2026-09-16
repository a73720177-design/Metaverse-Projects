import asyncio
import zipfile
import pytest
from app.services.upload_validation import validate_container, UploadLimitError
from app.services.parser_process import parse_in_process


def test_wrong_pdf_signature_and_mime_rejected(tmp_path):
    path = tmp_path / 'file.pdf'
    path.write_bytes(b'not a pdf')
    with pytest.raises(ValueError, match='PDF'):
        validate_container(path, 'application/pdf')
    path.write_bytes(b'%PDF-1.4')
    with pytest.raises(ValueError, match='MIME'):
        validate_container(path, 'application/zip')


def test_office_zip_bomb_is_rejected_before_parser(tmp_path):
    path = tmp_path / 'file.docx'
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('[Content_Types].xml', '<Types/>')
        archive.writestr('word/document.xml', 'a' * 1_000_000)
    with pytest.raises(UploadLimitError, match='압축률'):
        validate_container(path, 'application/zip')


def test_office_expanded_budget_and_internal_type(tmp_path, monkeypatch):
    path = tmp_path / 'file.pptx'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('[Content_Types].xml', '<Types/>')
        archive.writestr('word/document.xml', 'body')
    with pytest.raises(ValueError, match='내부 Office'):
        validate_container(path, None)
    monkeypatch.setenv('UPLOAD_MAX_EXPANDED_BYTES', '1')
    with pytest.raises(UploadLimitError, match='압축 해제'):
        validate_container(path, None)


def test_real_subprocess_extracts_docx(tmp_path, monkeypatch):
    from docx import Document
    monkeypatch.setenv('DOCUMENT_VISION_MODE', 'off')
    path = tmp_path / 'real.docx'
    document = Document()
    document.add_paragraph('검증 가능한 발표 근거')
    document.save(path)
    validate_container(path, None)
    parsed = asyncio.run(parse_in_process(path, path.name))
    assert '검증 가능한 발표 근거' in parsed.full_text


def test_timeout_kills_parser_process(monkeypatch):
    class Process:
        returncode = None
        pid = 321
        killed = False
        async def communicate(self):
            await asyncio.Event().wait()
        async def wait(self):
            self.returncode = -9
    process = Process()
    async def start(*args, **kwargs):
        return process
    async def terminate(target):
        target.killed = True
        target.returncode = -9
    monkeypatch.setattr('app.services.parser_process.asyncio.create_subprocess_exec', start)
    monkeypatch.setattr('app.services.parser_process._terminate_process_tree', terminate)
    monkeypatch.setenv('PARSER_TIMEOUT_SECONDS', '0')
    with pytest.raises(ValueError, match='시간 제한'):
        asyncio.run(parse_in_process('unused', 'unused.pdf'))
    assert process.killed and process.returncode == -9
