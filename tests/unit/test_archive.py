"""Safe zip unpacking for multi-document upload (cani_shared.archive): supported
entries surface as ArchiveEntry with sniffed content types; unsupported/dangerous
entries are skipped with reasons; whole-archive problems raise ArchiveValidationError.
"""

from __future__ import annotations

import io
import zipfile

import pytest
from cani_shared.archive import (
    MAX_ARCHIVE_ENTRIES,
    MAX_ENTRY_BYTES,
    ArchiveValidationError,
    extract_archive,
)

PDF_BYTES = b"%PDF-1.4\nfake pdf body"
JPEG_BYTES = b"\xff\xd8\xff\xe0fake jpeg body"
PNG_BYTES = b"\x89PNG\r\n\x1a\nfake png body"


def make_zip(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buffer.getvalue()


def test_mixed_supported_types_extracted():
    raw = make_zip({"lease.pdf": PDF_BYTES, "scan.jpg": JPEG_BYTES, "chart.png": PNG_BYTES})
    entries, skipped = extract_archive(raw)
    assert not skipped
    assert {(e.filename, e.content_type) for e in entries} == {
        ("lease.pdf", "application/pdf"),
        ("scan.jpg", "image/jpeg"),
        ("chart.png", "image/png"),
    }


def test_content_type_sniffed_from_magic_not_extension():
    raw = make_zip({"mislabeled.png": PDF_BYTES})
    entries, _ = extract_archive(raw)
    assert entries[0].content_type == "application/pdf"
    assert entries[0].extension == "pdf"


def test_unsupported_entries_skipped_with_reason():
    raw = make_zip({"notes.txt": b"plain text", "lease.pdf": PDF_BYTES})
    entries, skipped = extract_archive(raw)
    assert [e.filename for e in entries] == ["lease.pdf"]
    assert skipped[0].filename == "notes.txt"
    assert "unsupported" in skipped[0].reason


def test_directory_components_stripped_from_entry_names():
    raw = make_zip({"docs/2026/../../../etc/lease.pdf": PDF_BYTES})
    entries, _ = extract_archive(raw)
    assert entries[0].filename == "lease.pdf"


def test_hidden_and_metadata_entries_skipped():
    raw = make_zip({"__MACOSX/.hidden.pdf": PDF_BYTES, "lease.pdf": PDF_BYTES})
    entries, skipped = extract_archive(raw)
    assert [e.filename for e in entries] == ["lease.pdf"]
    assert len(skipped) == 1


def test_nested_archive_skipped_not_recursed():
    inner = make_zip({"inner.pdf": PDF_BYTES})
    raw = make_zip({"nested.zip": inner, "lease.pdf": PDF_BYTES})
    entries, skipped = extract_archive(raw)
    assert [e.filename for e in entries] == ["lease.pdf"]
    assert "nested archives" in skipped[0].reason


def test_empty_entry_skipped():
    raw = make_zip({"empty.pdf": b"", "lease.pdf": PDF_BYTES})
    entries, skipped = extract_archive(raw)
    assert [e.filename for e in entries] == ["lease.pdf"]
    assert skipped[0].reason == "empty file"


def test_not_a_zip_rejected():
    with pytest.raises(ArchiveValidationError):
        extract_archive(b"%PDF-1.4 definitely not a zip")


def test_empty_archive_rejected():
    with pytest.raises(ArchiveValidationError):
        extract_archive(make_zip({}))


def test_too_many_entries_rejected():
    raw = make_zip({f"doc-{i}.pdf": PDF_BYTES for i in range(MAX_ARCHIVE_ENTRIES + 1)})
    with pytest.raises(ArchiveValidationError):
        extract_archive(raw)


def test_zip_bomb_entry_skipped_by_capped_read():
    # Highly compressible payload just over the per-entry cap: the header may claim
    # anything, but the capped read stops at MAX_ENTRY_BYTES + 1 and skips the entry.
    bomb = b"\x00" * (MAX_ENTRY_BYTES + 1024)
    raw = make_zip({"bomb.bin": bomb, "lease.pdf": PDF_BYTES})
    entries, skipped = extract_archive(raw)
    assert [e.filename for e in entries] == ["lease.pdf"]
    assert "exceeds" in skipped[0].reason


def test_total_unpacked_size_capped():
    # Each entry is under the per-entry cap, but together they blow the archive total.
    # Payloads must differ (identical zeros dedupe nothing here, but keep it realistic).
    big = MAX_ENTRY_BYTES  # 25MB each, 5 entries = 125MB > 100MB total cap
    raw = make_zip({f"big-{i}.pdf": b"%PDF" + bytes([i]) * (big - 4) for i in range(5)})
    with pytest.raises(ArchiveValidationError):
        extract_archive(raw)
