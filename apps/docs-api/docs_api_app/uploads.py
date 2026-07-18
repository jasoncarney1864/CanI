"""Upload validation per docs/08-rag-pipeline-design.md §8.3 and
docs/14-security-and-compliance.md §14.8: strict file-type/size checks before any
processing. This is the first gate (malformed/mislabeled input); malware scanning
(§8.11) is a separate, later gate in the ingestion pipeline — the file is scanned
before extraction (see cani_shared.providers.scanner and ingestion_worker_app.pipeline).
"""

from __future__ import annotations

from dataclasses import dataclass

MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25MB — generous for the <25 page P95 target in §8.12

_ALLOWED = {
    "application/pdf": b"%PDF",
    "image/jpeg": b"\xff\xd8\xff",
    "image/png": b"\x89PNG",
    # A zip of multiple supported documents; unpacked (with strict limits) by the
    # ingestion worker, which registers each entry as its own document (§8.3).
    "application/zip": b"PK\x03\x04",
}

# Browsers on Windows commonly declare zips as x-zip-compressed; normalize to the
# canonical type so everything downstream (source_type checks) sees one value.
_CONTENT_TYPE_ALIASES = {"application/x-zip-compressed": "application/zip"}


class UploadValidationError(Exception):
    pass


@dataclass
class ValidatedUpload:
    content_type: str
    extension: str


_EXTENSION_BY_TYPE = {
    "application/pdf": "pdf",
    "image/jpeg": "jpg",
    "image/png": "png",
    "application/zip": "zip",
}


def validate_upload(*, content_type: str, size_bytes: int, head_bytes: bytes) -> ValidatedUpload:
    content_type = _CONTENT_TYPE_ALIASES.get(content_type, content_type)
    if content_type not in _ALLOWED:
        raise UploadValidationError(f"unsupported content type: {content_type}")
    if size_bytes > MAX_UPLOAD_BYTES:
        raise UploadValidationError(f"file exceeds max size of {MAX_UPLOAD_BYTES} bytes")
    if size_bytes == 0:
        raise UploadValidationError("empty file")
    magic = _ALLOWED[content_type]
    if not head_bytes.startswith(magic):
        raise UploadValidationError("file content does not match declared content type")
    return ValidatedUpload(content_type=content_type, extension=_EXTENSION_BY_TYPE[content_type])
