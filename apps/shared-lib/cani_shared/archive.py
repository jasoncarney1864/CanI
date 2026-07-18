"""Safe ZIP unpacking for multi-document upload (docs/08-rag-pipeline-design.md §8.3).

A user can upload one .zip containing several supported documents; the ingestion worker
unpacks it and registers each supported entry as its own document, which then flows
through the ordinary pipeline (malware scan included) as if uploaded individually.

Unpacking is deliberately paranoid, per docs/14-security-and-compliance.md §14.8:
- entry count, per-entry decompressed size, and total decompressed size are capped
  (zip-bomb protection — declared sizes are never trusted, reads are hard-capped);
- entry names are flattened to base names (path traversal is structurally impossible);
- nested archives are refused rather than recursed into;
- each entry's real content type is sniffed from magic bytes, never from its extension.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass

ZIP_CONTENT_TYPE = "application/zip"

MAX_ARCHIVE_ENTRIES = 50
# Per-entry cap matches the single-file upload limit (docs_api_app.uploads.MAX_UPLOAD_BYTES).
MAX_ENTRY_BYTES = 25 * 1024 * 1024
MAX_TOTAL_UNPACKED_BYTES = 100 * 1024 * 1024

# Same magic-byte whitelist as the upload gate: PDF, JPEG, PNG.
_MAGIC_TO_TYPE: tuple[tuple[bytes, str, str], ...] = (
    (b"%PDF", "application/pdf", "pdf"),
    (b"\xff\xd8\xff", "image/jpeg", "jpg"),
    (b"\x89PNG", "image/png", "png"),
)


class ArchiveValidationError(Exception):
    """The archive as a whole is unusable — mapped to a permanent job failure."""


@dataclass
class ArchiveEntry:
    filename: str  # base name only — directory components are stripped
    content_type: str
    extension: str
    data: bytes


@dataclass
class SkippedEntry:
    filename: str
    reason: str


def extract_archive(raw: bytes) -> tuple[list[ArchiveEntry], list[SkippedEntry]]:
    """Unpack a zip upload into supported document entries + a skip report.

    Raises ArchiveValidationError for whole-archive problems (corrupt file, too many
    entries, decompressed payload too large). Per-entry problems (unsupported type,
    oversized entry, encrypted entry) are reported as skips, not failures, so one odd
    file doesn't sink the rest of the archive.
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as exc:
        raise ArchiveValidationError(f"not a valid zip archive: {exc}") from exc

    infos = [i for i in zf.infolist() if not i.is_dir()]
    if not infos:
        raise ArchiveValidationError("archive contains no files")
    if len(infos) > MAX_ARCHIVE_ENTRIES:
        raise ArchiveValidationError(
            f"archive has {len(infos)} files (max {MAX_ARCHIVE_ENTRIES})"
        )

    entries: list[ArchiveEntry] = []
    skipped: list[SkippedEntry] = []
    total_bytes = 0
    for info in infos:
        # Base name only: "../../etc/passwd" or "docs\evil.pdf" become plain file names.
        name = info.filename.replace("\\", "/").rsplit("/", 1)[-1]
        if not name or name.startswith("."):
            skipped.append(SkippedEntry(filename=info.filename, reason="hidden or unnamed entry"))
            continue
        if info.flag_bits & 0x1:
            skipped.append(SkippedEntry(filename=name, reason="encrypted entry"))
            continue

        # Hard-capped read — the declared uncompressed size in the header can lie.
        with zf.open(info) as fh:
            data = fh.read(MAX_ENTRY_BYTES + 1)
        if len(data) > MAX_ENTRY_BYTES:
            skipped.append(
                SkippedEntry(filename=name, reason=f"entry exceeds {MAX_ENTRY_BYTES} bytes uncompressed")
            )
            continue
        if not data:
            skipped.append(SkippedEntry(filename=name, reason="empty file"))
            continue

        total_bytes += len(data)
        if total_bytes > MAX_TOTAL_UNPACKED_BYTES:
            raise ArchiveValidationError(
                f"archive exceeds {MAX_TOTAL_UNPACKED_BYTES} bytes uncompressed"
            )

        if data.startswith(b"PK\x03\x04"):
            skipped.append(SkippedEntry(filename=name, reason="nested archives are not unpacked"))
            continue
        sniffed = next(
            ((ct, ext) for magic, ct, ext in _MAGIC_TO_TYPE if data.startswith(magic)), None
        )
        if sniffed is None:
            skipped.append(SkippedEntry(filename=name, reason="unsupported file type"))
            continue

        content_type, extension = sniffed
        entries.append(
            ArchiveEntry(filename=name, content_type=content_type, extension=extension, data=data)
        )

    return entries, skipped
