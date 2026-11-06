from collections import Counter

import pytest

from app.ingestion.normalizer import normalize_record
from app.privacy.pipeline import redact_record
from app.privacy.redactor import RedactionConfig, Redactor, contains_secret


@pytest.fixture()
def r():
    return Redactor()


@pytest.mark.parametrize(
    "text,placeholder",
    [
        ("contact me at jane.doe@example.com please", "[REDACTED_EMAIL]"),
        ("call +1 212-555-0187 now", "[REDACTED_PHONE]"),
        ("call (415) 555-0134", "[REDACTED_PHONE]"),
        ("india +91 98765 43210", "[REDACTED_PHONE]"),
        ("key sk-proj-abcdefghijklmnopqrstuvwx", "[REDACTED_API_KEY]"),
        ("aws AKIAABCDEFGHIJKLMNOP", "[REDACTED_API_KEY]"),
        ("gh ghp_abcdefghijklmnopqrstuvwxyz0123", "[REDACTED_API_KEY]"),
        ("Authorization: Bearer abcdefghijklmnop1234567890", "[REDACTED_TOKEN]"),
        ("password=hunter2", "[REDACTED_SECRET]"),
        ("card 4111 1111 1111 1111", "[REDACTED_CARD]"),
        ("ssn 123-45-6789", "[REDACTED_SSN]"),
        ("from 203.0.113.42", "[REDACTED_IP]"),
        (
            "jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
            "[REDACTED_TOKEN]",
        ),
    ],
)
def test_detects_sensitive_values(r, text, placeholder):
    out = r.redact_text(text)
    assert placeholder in out.text
    assert sum(out.counts.values()) >= 1


def test_known_limitation_dotted_versions_look_like_ips(r):
    # Documented limitation: 4-part version strings are valid IPv4 addresses, so they are
    # redacted. We accept over-redaction here rather than risk leaking a real IP.
    assert "[REDACTED_IP]" in r.redact_text("Version 1.2.3.4 of the app").text


@pytest.mark.parametrize(
    "text",
    [
        "Your order total is $42.50",
        "Meeting at 2026-09-01 10:00",
        "We operate in us-east and eu-west",
        "card number 1234 5678 9012 3456",  # fails Luhn
        "999.999.999.999",  # invalid IP
    ],
)
def test_no_false_positive_on_ordinary_text(r, text):
    out = r.redact_text(text)
    assert "[REDACTED_CARD]" not in out.text
    assert "[REDACTED_IP]" not in out.text
    assert "[REDACTED_EMAIL]" not in out.text


def test_ip_redaction_can_be_disabled():
    r = Redactor(RedactionConfig(redact_ip_addresses=False))
    assert "203.0.113.42" in r.redact_text("ip 203.0.113.42").text


def test_custom_pattern():
    r = Redactor(RedactionConfig(custom_patterns={"employee_id": r"EMP-\d{6}"}))
    out = r.redact_text("employee EMP-123456 reported")
    assert "[REDACTED_EMPLOYEE_ID]" in out.text


def test_sensitive_metadata_fields_and_nested_values(r):
    counts: Counter[str] = Counter()
    out = r.redact_value(
        {"user_email": "a@b.com", "nested": {"note": "mail x@y.org"}, "list": ["ok", "z@z.io"]}, counts
    )
    assert out["user_email"] == "[REDACTED_FIELD]"
    assert out["nested"]["note"] == "mail [REDACTED_EMAIL]"
    assert out["list"][1] == "[REDACTED_EMAIL]"


def test_redact_record_all_fields_and_pseudonymised_ids(r):
    rec = normalize_record(
        {
            "trace_id": "session-bob@example.com",
            "user_input": "I am bob@example.com",
            "assistant_response": "Sent to bob@example.com",
            "system_prompt": "admin key sk-abcdefghijklmnopqrstu",
            "error": "failed for 10.0.0.1",
            "metadata": {"phone": "555-0100"},
        },
        1,
    )
    counts = redact_record(rec, r)
    for value in (rec.user_input, rec.assistant_response, rec.system_prompt, rec.error_message, rec.trace_id):
        assert "bob@example.com" not in value and "sk-abc" not in value and "10.0.0.1" not in value
    assert rec.trace_id.startswith("pseudo-")
    assert rec.redaction_count == sum(counts.values()) >= 5
    assert rec.raw_payload is None  # raw content is not preserved by default


def test_pseudonyms_are_stable_and_distinct(r):
    a1 = normalize_record({"trace_id": "a@x.com", "input": "1"}, 1)
    a2 = normalize_record({"trace_id": "a@x.com", "input": "2"}, 2)
    b = normalize_record({"trace_id": "b@x.com", "input": "3"}, 3)
    for rec in (a1, a2, b):
        redact_record(rec, r)
    assert a1.trace_id == a2.trace_id != b.trace_id


def test_raw_preserved_only_when_enabled(r):
    rec = normalize_record({"input": "mail a@b.com"}, 1)
    redact_record(rec, r, preserve_raw=True)
    assert "a@b.com" in rec.raw_payload
    assert "a@b.com" not in rec.user_input


def test_contains_secret():
    assert contains_secret("token sk-abcdefghijklmnopqrstuv")
    assert not contains_secret("hello world")


@pytest.mark.parametrize("text", ["phone +91 98765 43210.", "call (415) 555-0134, thanks", "ring +14155550134!"])
def test_phone_followed_by_punctuation(r, text):
    assert "[REDACTED_PHONE]" in r.redact_text(text).text


def test_decimal_numbers_not_phone(r):
    assert "[REDACTED_PHONE]" not in r.redact_text("ratio 12.5 and 3.14159").text
