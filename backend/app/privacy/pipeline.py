"""Apply redaction to normalized records."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from collections import Counter

from app.ingestion.schema import NormalizedRecord
from app.privacy.redactor import Redactor

# Per-process salt: identifiers containing PII become stable within a run (so traces still
# group correctly) but cannot be reversed with a dictionary attack on the hash.
_ID_SALT = secrets.token_bytes(16)

_TEXT_FIELDS = ("user_input", "system_prompt", "assistant_response", "error_message")


def redact_record(rec: NormalizedRecord, redactor: Redactor, preserve_raw: bool = False) -> Counter[str]:
    counts: Counter[str] = Counter()
    if preserve_raw:
        rec.raw_payload = json.dumps(
            {f: getattr(rec, f) for f in _TEXT_FIELDS} | {"metadata": rec.metadata}, ensure_ascii=False, default=str
        )
    for name in _TEXT_FIELDS:
        value = getattr(rec, name)
        if value:
            res = redactor.redact_text(value)
            counts.update(res.counts)
            setattr(rec, name, res.text)
    rec.metadata = redactor.redact_value(rec.metadata, counts)
    # Identifiers occasionally embed emails (e.g. session ids). Replace them with a salted
    # pseudonym instead of a placeholder so distinct traces are not merged together.
    for name in ("trace_id", "request_id"):
        value = getattr(rec, name)
        if value:
            res = redactor.redact_text(value)
            if res.counts:
                counts.update(res.counts)
                digest = hmac.new(_ID_SALT, value.encode("utf-8"), hashlib.sha256).hexdigest()[:16]
                setattr(rec, name, f"pseudo-{digest}")
    rec.redaction_count = sum(counts.values())
    return counts
