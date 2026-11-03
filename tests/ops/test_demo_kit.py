"""ops/demo-kit: the generator reproduces the committed kit, and each file reads as a sample.

Text checks read the PDFs with poppler's ``pdftotext``/``pdfinfo``; they are
skipped where poppler isn't installed.
"""

from __future__ import annotations

import importlib.util
import logging
import shutil
import subprocess
import sys
import warnings
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
KIT_DIR = REPO_ROOT / "ops" / "demo-kit"
FILES = KIT_DIR / "files"
SAMPLE_MARK = "MẪU — DỮ LIỆU GIẢ LẬP"

needs_poppler = pytest.mark.skipif(
    shutil.which("pdftotext") is None or shutil.which("pdfinfo") is None,
    reason="poppler (pdftotext, pdfinfo) not available",
)


@pytest.fixture(scope="module")
def generator():
    spec = importlib.util.spec_from_file_location(
        "demo_kit_generator", KIT_DIR / "generator" / "generate.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _text(path: Path) -> str:
    return subprocess.run(
        ["pdftotext", "-layout", str(path), "-"], check=True, capture_output=True, text=True
    ).stdout


def _info(path: Path) -> str:
    return subprocess.run(
        ["pdfinfo", str(path)], check=True, capture_output=True, text=True
    ).stdout


def test_rerunning_the_generator_reproduces_the_committed_files(generator, tmp_path, caplog):
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        with caplog.at_level(logging.WARNING):
            generator.main(["--out", str(tmp_path)])

    # fpdf2 logs a warning for every character the font has no glyph for.
    assert not caplog.records, [record.getMessage() for record in caplog.records]
    produced = sorted(path.name for path in tmp_path.iterdir())
    assert produced == sorted(path.name for path in FILES.glob("*.pdf"))
    for name in produced:
        assert (tmp_path / name).read_bytes() == (FILES / name).read_bytes(), (
            f"{name} differs from the committed file; rerun "
            "ops/demo-kit/generator/generate.py and commit the result"
        )


@needs_poppler
@pytest.mark.parametrize(
    "name",
    [
        "bao-gia-sua-thang-may-mau.pdf",
        "chung-tu-thanh-toan-mau.pdf",
        "thong-bao-tam-ngung-thang-may.pdf",
    ],
)
def test_every_kit_file_is_a_one_page_text_pdf_marked_as_a_sample(name):
    path = FILES / name
    assert path.read_bytes().startswith(b"%PDF-")
    assert "Pages:           1" in _info(path)
    assert SAMPLE_MARK in _text(path)


@needs_poppler
def test_the_quotation_reads_with_its_vietnamese_diacritics():
    text = _text(FILES / "bao-gia-sua-thang-may-mau.pdf")
    assert "CÔNG TY TNHH THANG MÁY MẪU" in text
    assert "BÁO GIÁ SỬA CHỮA THANG MÁY" in text
    assert "Thang máy rung lắc mạnh khi chạy." in text
    assert "560.000.000" in text
    assert "Năm trăm sáu mươi triệu đồng" in text


@needs_poppler
def test_the_transfer_proof_pays_the_kit_contractor_from_an_obviously_fake_account():
    text = _text(FILES / "chung-tu-thanh-toan-mau.pdf")
    assert "CHỨNG TỪ THANH TOÁN" in text
    assert "BẢN MẪU GIẢ LẬP" in text
    assert "Công ty TNHH Thang máy Mẫu" in text
    assert "560.000.000 VND" in text
    assert "0000 0000 0000 (số tài khoản giả)" in text
    assert "0000 0000 0001 (số tài khoản giả)" in text


@needs_poppler
def test_the_notice_is_an_a5_page():
    info = _info(FILES / "thong-bao-tam-ngung-thang-may.pdf")
    # A5 is 148 x 210 mm: 419.53 x 595.28 pt.
    assert "Page size:       419.53 x 595.28 pts" in info
    assert "TẠM NGỪNG" in _text(FILES / "thong-bao-tam-ngung-thang-may.pdf")


@pytest.mark.parametrize(
    ("amount", "words"),
    [
        (560_000_000, "Năm trăm sáu mươi triệu đồng"),
        (1_000_000_000, "Một tỷ đồng"),
        (215_000, "Hai trăm mười lăm nghìn đồng"),
        (1_005_041, "Một triệu không trăm linh năm nghìn không trăm bốn mươi mốt đồng"),
        (24, "Hai mươi tư đồng"),
    ],
)
def test_amounts_are_read_aloud_in_vietnamese(generator, amount, words):
    assert generator.vnd_in_words(amount) == words
