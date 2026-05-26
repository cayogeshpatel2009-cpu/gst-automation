from __future__ import annotations

from pathlib import Path

import pytest

from gst_automation.browser.sandbox import DownloadSandbox


def test_download_sandbox_allocate_and_cleanup(tmp_path: Path) -> None:
    sb = DownloadSandbox(root=tmp_path, download_timeout_seconds=10)
    ws, downloads = sb.allocate()
    assert ws.exists()
    assert downloads.exists()
    sb.cleanup(ws)
    assert not ws.exists()


def test_download_finalize_hash(tmp_path: Path) -> None:
    sb = DownloadSandbox(root=tmp_path / "root", download_timeout_seconds=10)
    ws, downloads = sb.allocate()
    f = downloads / "file.txt"
    f.write_text("hello", encoding="utf-8")
    out = sb.finalize_file(tmp_path=f, final_dir=tmp_path / "final", final_name="x.txt")
    assert out.path.exists()
    assert out.byte_size > 0
    assert len(out.sha256_hex) == 64
    sb.cleanup(ws)

