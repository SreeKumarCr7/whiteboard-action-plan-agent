import base64
import binascii
import os

import boto3
from botocore.exceptions import BotoCoreError, ClientError


class OCRConfigError(Exception):
    """Raised when AWS credentials/configuration are missing or invalid."""


class OCRBadImageError(Exception):
    """Raised when the provided image data cannot be decoded."""


class OCRServiceError(Exception):
    """Raised when AWS Textract itself fails."""


def _get_textract_client():
    access_key = os.getenv("AWS_ACCESS_KEY_ID")
    secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")
    region = os.getenv("AWS_REGION")

    if not (access_key and secret_key):
        raise OCRConfigError(
            "AWS credentials are not configured. Set AWS_ACCESS_KEY_ID and "
            "AWS_SECRET_ACCESS_KEY as environment variables."
        )
    if not region:
        raise OCRConfigError(
            "AWS region is not configured. Set AWS_REGION as an environment "
            "variable (e.g. us-east-1)."
        )

    try:
        return boto3.client(
            "textract",
            region_name=region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )
    except BotoCoreError as exc:
        raise OCRConfigError(f"Failed to initialize AWS Textract client: {exc}") from exc


def run_textract(image_bytes: bytes) -> dict:
    """Run AWS Textract DetectDocumentText on raw image bytes.

    Returns {"raw_text": str, "lines": list[str]}.
    """
    client = _get_textract_client()

    try:
        response = client.detect_document_text(Document={"Bytes": image_bytes})
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "UnknownError")
        message = exc.response.get("Error", {}).get("Message", str(exc))
        raise OCRServiceError(
            f"Textract request failed ({error_code}): {message}"
        ) from exc
    except BotoCoreError as exc:
        raise OCRServiceError(f"Textract request failed: {exc}") from exc

    blocks = response.get("Blocks", [])
    # A Word block is the smallest detected unit; LINE blocks are the natural
    # grouping. Order is preserved as Textract returns them.
    line_texts = [
        block.get("Text", "").strip()
        for block in blocks
        if block.get("BlockType") == "LINE" and block.get("Text")
    ]

    raw_text = "\n".join(line_texts)
    return {"raw_text": raw_text, "lines": line_texts}


def decode_image_from_base64(data: str) -> bytes:
    """Decode a base64 string (with optional data-URI prefix) to raw bytes."""
    if not data or not isinstance(data, str):
        raise OCRBadImageError("No image data provided.")

    # Strip a possible data URI prefix like "data:image/png;base64,".
    if "," in data and data.strip().startswith("data:"):
        data = data.split(",", 1)[1]

    try:
        return base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise OCRBadImageError("Image data is not valid base64.") from exc
