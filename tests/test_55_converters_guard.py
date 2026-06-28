"""Tests for file_converter, ollama_guard, crash_db — Copyright 2026 ILX Studio — MIT License"""
from __future__ import annotations
import sys
import time
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.core import file_converter  # noqa: E402
import app.core.ollama_guard as og  # noqa: E402
import app.core.crash_db as crash_db  # noqa: E402

# ---------------------------------------------------------------------------
# file_converter
# ---------------------------------------------------------------------------

def test_read_pdf_missing_pypdf(tmp_path):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF fake")
    with patch.dict(sys.modules, {"pypdf": None}):
        result = file_converter.read_pdf(str(pdf))
    assert result["ok"] is False
    assert "pypdf" in result["error"].lower()


def test_read_pdf_success(tmp_path):
    mock_page = MagicMock()
    mock_page.extract_text.return_value = "Hello PDF"
    mock_reader = MagicMock()
    mock_reader.pages = [mock_page]
    mock_pypdf = MagicMock()
    mock_pypdf.PdfReader.return_value = mock_reader
    with patch.dict(sys.modules, {"pypdf": mock_pypdf}):
        result = file_converter.read_pdf(str(tmp_path / "doc.pdf"))
    assert result["ok"] is True
    assert "Hello PDF" in result["text"]


def test_read_pdf_exception(tmp_path):
    mock_pypdf = MagicMock()
    mock_pypdf.PdfReader.side_effect = Exception("corrupt")
    with patch.dict(sys.modules, {"pypdf": mock_pypdf}):
        result = file_converter.read_pdf(str(tmp_path / "doc.pdf"))
    assert result["ok"] is False
    assert "corrupt" in result["error"]


def test_read_docx_missing_python_docx(tmp_path):
    with patch.dict(sys.modules, {"docx": None}):
        result = file_converter.read_docx(str(tmp_path / "doc.docx"))
    assert result["ok"] is False
    assert "python-docx" in result["error"].lower()


def test_read_docx_success(tmp_path):
    mock_para = MagicMock()
    mock_para.text = "Hello DOCX"
    mock_doc_obj = MagicMock()
    mock_doc_obj.paragraphs = [mock_para]
    mock_docx_mod = MagicMock()
    mock_docx_mod.Document.return_value = mock_doc_obj
    with patch.dict(sys.modules, {"docx": mock_docx_mod}):
        result = file_converter.read_docx(str(tmp_path / "doc.docx"))
    assert result["ok"] is True
    assert "Hello DOCX" in result["text"]


def test_read_xlsx_missing_openpyxl(tmp_path):
    with patch.dict(sys.modules, {"openpyxl": None}):
        result = file_converter.read_xlsx(str(tmp_path / "data.xlsx"))
    assert result["ok"] is False
    assert "openpyxl" in result["error"].lower()


def test_read_xlsx_success(tmp_path):
    mock_ws = MagicMock()
    mock_ws.iter_rows.return_value = [("A", "B")]
    mock_wb = MagicMock()
    mock_wb.sheetnames = ["Sheet1"]
    mock_wb.__getitem__ = MagicMock(return_value=mock_ws)
    mock_openpyxl = MagicMock()
    mock_openpyxl.load_workbook.return_value = mock_wb
    with patch.dict(sys.modules, {"openpyxl": mock_openpyxl}):
        result = file_converter.read_xlsx(str(tmp_path / "data.xlsx"))
    assert result["ok"] is True
    assert "Sheet1" in result["sheets"]


def test_read_png_missing_pillow(tmp_path):
    with patch.dict(sys.modules, {"PIL": None, "PIL.Image": None}):
        result = file_converter.read_png(str(tmp_path / "img.png"))
    assert result["ok"] is False
    assert "Pillow" in result["error"]


def test_read_png_success(tmp_path):
    mock_img = MagicMock()
    mock_img.size = (800, 600)
    mock_img.mode = "RGB"
    mock_img.__enter__ = MagicMock(return_value=mock_img)
    mock_img.__exit__ = MagicMock(return_value=False)
    mock_pil_image = MagicMock()
    mock_pil_image.open.return_value = mock_img
    mock_pil = MagicMock()
    mock_pil.Image = mock_pil_image
    with patch.dict(sys.modules, {"PIL": mock_pil, "PIL.Image": mock_pil_image}):
        result = file_converter.read_png(str(tmp_path / "img.png"))
    assert result["ok"] is True
    assert result["width"] == 800
    assert "800x600" in result["text"]


# ---------------------------------------------------------------------------
# ollama_guard
# ---------------------------------------------------------------------------

def _reset():
    og._failures = 0
    og._opened_at = None
    og._state = "closed"


def test_with_backoff_success():
    _reset()
    assert og.with_backoff(lambda: 99) == 99


def test_record_success_clears_state():
    _reset()
    og._failures = 2
    og._record_success()
    assert og._failures == 0
    assert og._state == "closed"


def test_circuit_state_closed_initially():
    _reset()
    assert og.circuit_state() == "closed"


def test_open_circuit_raises_immediately():
    _reset()
    og._state = "open"
    og._opened_at = time.monotonic()
    og._failures = og._FAILURE_THRESHOLD
    with pytest.raises(RuntimeError, match="Circuit breaker OPEN"):
        og.with_backoff(lambda: 1)
    _reset()


def test_with_backoff_retries_on_failure():
    _reset()
    calls = []
    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise ValueError("not yet")
        return "ok"
    with patch("time.sleep"):
        result = og.with_backoff(flaky)
    assert result == "ok"
    assert len(calls) == 3


# ---------------------------------------------------------------------------
# crash_db
# ---------------------------------------------------------------------------

def _patched_db(tmp_path: Path):
    return patch.object(crash_db, "_DB_PATH", tmp_path / "crashes.db")


def test_crash_db_record_and_list(tmp_path):
    with _patched_db(tmp_path):
        crash_db.record("cmd_x", 1, "Traceback: Error")
        entries = crash_db.list_crashes(limit=10)
    assert len(entries) == 1
    assert entries[0]["command"] == "cmd_x"
    assert entries[0]["exit_code"] == 1


def test_crash_db_newest_first(tmp_path):
    with _patched_db(tmp_path):
        crash_db.record("cmd_a", 1, "err a")
        crash_db.record("cmd_b", 2, "err b")
        entries = crash_db.list_crashes(limit=10)
    assert entries[0]["command"] == "cmd_b"


def test_crash_db_clear(tmp_path):
    with _patched_db(tmp_path):
        crash_db.record("doomed", 3, "fatal")
        crash_db.record("also_doomed", 4, "fatal2")
        deleted = crash_db.clear_crashes()
        remaining = crash_db.list_crashes(limit=10)
    assert deleted == 2
    assert remaining == []


def test_crash_db_group_summary(tmp_path):
    with _patched_db(tmp_path):
        tb = "File test.py line 1\nRuntimeError: boom"
        crash_db.record("cmd", 1, tb)
        crash_db.record("cmd", 1, tb)
        summary = crash_db.group_summary()
    assert summary[0]["count"] == 2
