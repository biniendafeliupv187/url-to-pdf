"""
Integration tests for convert_url_to_pdf().

These tests make REAL network requests and invoke Playwright.
They verify the core invariant: every PDF produced must be non-blank.

Mark: @pytest.mark.integration — run separately from fast unit tests.

Run with:
    python3 -m pytest scripts/tests/test_integration.py -v -s
"""
import asyncio
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from convert_to_pdf import convert_url_to_pdf

# Minimum size threshold — a truly blank PDF is < 5 KB; real content is >> 50 KB
MIN_PDF_BYTES = 50_000  # 50 KB


def find_pdfs(directory: str) -> list[str]:
    """Return list of .pdf paths found recursively under directory."""
    pdfs = []
    for folder, _, files in os.walk(directory):
        for f in files:
            if f.endswith(".pdf"):
                pdfs.append(os.path.join(folder, f))
    return pdfs


pytestmark = pytest.mark.integration


class TestNonBlankPdf:
    """Both login-required and public URLs must produce non-blank PDFs."""

    def _run(self, url: str) -> list[str]:
        with tempfile.TemporaryDirectory() as tmpdir:
            asyncio.run(convert_url_to_pdf([url], tmpdir, wait_after_load=10))
            pdfs = find_pdfs(tmpdir)
            # Copy sizes before tmpdir is deleted
            sizes = [(p, os.path.getsize(p)) for p in pdfs]
        return sizes

    def test_public_url_juejin_produces_non_blank_pdf(self):
        """
        Juejin article is publicly accessible (no login required).
        PDF must exist and exceed the minimum size threshold.
        """
        url = (
            "https://juejin.cn/post/6844903598350925831"
            "?searchId=20260111212247A523C2864F9115258F22"
        )
        results = self._run(url)
        assert len(results) == 1, "Expected exactly one PDF to be generated"
        pdf_path, size = results[0]
        assert size > MIN_PDF_BYTES, (
            f"PDF is likely blank: {size} bytes < {MIN_PDF_BYTES} bytes. "
            f"File: {pdf_path}"
        )
        # Filename must contain something meaningful (not "untitled")
        pdf_name = os.path.basename(pdf_path)
        assert "untitled" not in pdf_name.lower(), (
            f"PDF filename fell back to untitled: {pdf_name}"
        )

    def test_geekbang_url_produces_non_blank_pdf_even_without_full_login(self):
        """
        Geekbang article — user may not be fully logged in, but the page
        renders enough content that the PDF must still exceed the threshold.
        If the PDF is blank, the conversion strategy needs fixing.
        """
        url = "https://time.geekbang.org/column/article/945358?cid=101113501"
        results = self._run(url)
        assert len(results) == 1, "Expected exactly one PDF to be generated"
        pdf_path, size = results[0]
        assert size > MIN_PDF_BYTES, (
            f"PDF is likely blank: {size} bytes < {MIN_PDF_BYTES} bytes. "
            f"File: {pdf_path}"
        )
        pdf_name = os.path.basename(pdf_path)
        assert "untitled" not in pdf_name.lower(), (
            f"PDF filename fell back to untitled: {pdf_name}"
        )
