import base64

import pytest

from app.ocr import (
    OCRBadImageError,
    OCRConfigError,
    OCRServiceError,
    decode_image_from_base64,
    run_textract,
)


def test_decode_image_from_base64():
    raw = b"hello-image"
    data = base64.b64encode(raw).decode()
    assert decode_image_from_base64(data) == raw


def test_decode_image_from_base64_with_data_uri_prefix():
    raw = b"hello-image"
    data = "data:image/png;base64," + base64.b64encode(raw).decode()
    assert decode_image_from_base64(data) == raw


def test_decode_image_from_base64_invalid():
    with pytest.raises(OCRBadImageError):
        decode_image_from_base64("not-base64!!!")


def test_decode_image_from_base64_empty():
    with pytest.raises(OCRBadImageError):
        decode_image_from_base64("")


def test_run_textract_returns_lines_in_order(monkeypatch):
    blocks = [
        {"BlockType": "PAGE"},
        {"BlockType": "LINE", "Text": "first line"},
        {"BlockType": "WORD", "Text": "ignored"},
        {"BlockType": "LINE", "Text": "second line"},
    ]

    class FakeClient:
        def detect_document_text(self, Document):
            return {"Blocks": blocks}

    monkeypatch.setattr("app.ocr._get_textract_client", lambda: FakeClient())
    result = run_textract(b"fake-bytes")
    assert result == {"raw_text": "first line\nsecond line", "lines": ["first line", "second line"]}


def test_run_textract_no_text(monkeypatch):
    class FakeClient:
        def detect_document_text(self, Document):
            return {"Blocks": []}

    monkeypatch.setattr("app.ocr._get_textract_client", lambda: FakeClient())
    result = run_textract(b"fake-bytes")
    assert result == {"raw_text": "", "lines": []}


def test_missing_credentials_raises_config_error(monkeypatch):
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
    monkeypatch.setenv("AWS_REGION", "us-east-1")

    from app.ocr import _get_textract_client

    with pytest.raises(OCRConfigError):
        _get_textract_client()


def test_missing_region_raises_config_error(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "ak")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "sk")
    monkeypatch.delenv("AWS_REGION", raising=False)

    from app.ocr import _get_textract_client

    with pytest.raises(OCRConfigError):
        _get_textract_client()


def test_run_textract_client_error(monkeypatch):
    from botocore.exceptions import ClientError

    error_response = {
        "Error": {"Code": "AccessDeniedException", "Message": "no perms"},
        "ResponseMetadata": {"HTTPStatusCode": 400},
    }

    class FakeClient:
        def detect_document_text(self, Document):
            raise ClientError(error_response, "DetectDocumentText")

    monkeypatch.setattr("app.ocr._get_textract_client", lambda: FakeClient())
    with pytest.raises(OCRServiceError) as exc_info:
        run_textract(b"fake-bytes")
    assert "AccessDeniedException" in str(exc_info.value)
