"""Upload validation per docs/08-rag-pipeline-design.md §8.3 and
docs/14-security-and-compliance.md §14.8: strict file-type/size checks before any
processing. Malware scanning (§8.11) is explicitly deferred for this MVP pass — see the
launch-readiness gap report — so this is a defense against malformed/mislabeled input,
not a substitute for AV scanning before production launch.
"""

from __future__ import annotations

from dataclasses import dataclass

MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25MB — generous for the <25 page P95 target in §8.12

_ALLOWED = {
    "application/pdf": b"%PDF",
    "image/jpeg": b"\xff\xd8\xff",
    "image/png": b"\x89PNG",
}


class UploadValidationError(Exception):
    pass


@dataclass
class ValidatedUpload:
    content_type: str
    extension: str


_EXTENSION_BY_TYPE = {"application/pdf": "pdf", "image/jpeg": "jpg", "image/png": "png"}


def validate_upload(*, content_type: str, size_bytes: int, head_bytes: bytes) -> ValidatedUpload:
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
