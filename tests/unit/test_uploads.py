import pytest
from docs_api_app.uploads import MAX_UPLOAD_BYTES, UploadValidationError, validate_upload


def test_valid_pdf_accepted():
    head = b"%PDF-1.4\n%..."
    result = validate_upload(content_type="application/pdf", size_bytes=1024, head_bytes=head)
    assert result.extension == "pdf"


def test_unsupported_content_type_rejected():
    with pytest.raises(UploadValidationError):
        validate_upload(content_type="application/zip", size_bytes=1024, head_bytes=b"PK\x03\x04")


def test_oversized_file_rejected():
    with pytest.raises(UploadValidationError):
        validate_upload(content_type="application/pdf", size_bytes=MAX_UPLOAD_BYTES + 1, head_bytes=b"%PDF")


def test_mismatched_magic_bytes_rejected():
    with pytest.raises(UploadValidationError):
        validate_upload(content_type="application/pdf", size_bytes=1024, head_bytes=b"\x89PNG\r\n")


def test_empty_file_rejected():
    with pytest.raises(UploadValidationError):
        validate_upload(content_type="application/pdf", size_bytes=0, head_bytes=b"")
