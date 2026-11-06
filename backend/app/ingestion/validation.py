"""Upload validation: size, extension, encoding and binary-content checks."""

from __future__ import annotations

from dataclasses import dataclass

SUPPORTED_EXTENSIONS = {
    ".jsonl": "jsonl",
    ".ndjson": "jsonl",
    ".json": "json",
    ".csv": "csv",
    ".log": "log",
    ".txt": "log",
}


class UploadValidationError(ValueError):
    """Raised when an uploaded file is rejected. Message is safe to show to users."""


@dataclass
class ValidatedUpload:
    text: str
    file_format: str
    size_bytes: int


def detect_format(filename: str, text: str) -> str:
    lower = filename.lower()
    for ext, fmt in SUPPORTED_EXTENSIONS.items():
        if lower.endswith(ext):
            if fmt == "log":
                # A .log/.txt file whose lines are JSON objects is really JSONL.
                first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
                return "jsonl" if first.startswith("{") else "log"
            return fmt
    raise UploadValidationError(
        f"Unsupported file type. Supported extensions: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
    )


def validate_upload(filename: str, content: bytes, max_bytes: int) -> ValidatedUpload:
    if len(content) == 0:
        raise UploadValidationError("Uploaded file is empty.")
    if len(content) > max_bytes:
        raise UploadValidationError(f"File exceeds the maximum upload size of {max_bytes // (1024 * 1024)} MB.")
    # Detect format by extension first so unsupported types fail fast.
    lower = filename.lower()
    if not any(lower.endswith(ext) for ext in SUPPORTED_EXTENSIONS):
        raise UploadValidationError(
            f"Unsupported file type. Supported extensions: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )
    sample = content[:8192]
    if b"\x00" in sample:
        raise UploadValidationError("File appears to be binary, not a text log file.")
    # Common executable / archive magic numbers.
    for magic in (b"MZ", b"PK\x03\x04", b"\x7fELF", b"%PDF", b"\x1f\x8b"):
        if content.startswith(magic):
            raise UploadValidationError("File appears to be binary, not a text log file.")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise UploadValidationError("File is not valid UTF-8 text.") from exc
    return ValidatedUpload(text=text, file_format=detect_format(filename, text), size_bytes=len(content))
