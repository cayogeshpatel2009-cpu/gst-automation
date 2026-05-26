from __future__ import annotations

from pathlib import Path

from gst_automation.storage.folder_manager import FolderManager


def test_folder_layout_sanitizes_segments() -> None:
    fm = FolderManager(folder_root=Path("D:/GST/Clients"))
    layout = fm.layout(client_name="ACME / Co", gstin="29ABCDE1234F1Z5", fy="2025-26", period_yyyy_mm="2026-05")
    assert "ACME - Co" not in str(layout.period_root)  # we sanitize slashes
    assert "ACME" in str(layout.period_root)

