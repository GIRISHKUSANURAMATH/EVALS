"""Configurable PII and secret redaction.

Every text field and metadata value is passed through the redactor *before* it is
persisted. Detected values are replaced with typed placeholders such as
``[REDACTED_EMAIL]``; the raw values are never stored unless raw preservation is
explicitly enabled.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RedactionRule:
    name: str
    pattern: re.Pattern[str]
    placeholder: str
    validator: Any = None  # optional callable(match_text) -> bool


def _luhn_ok(text: str) -> bool:
    digits = [int(c) for c in text if c.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    checksum = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    return checksum % 10 == 0


def _valid_ipv4(text: str) -> bool:
    parts = text.split(".")
    return len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts)


# Order matters: more specific secret patterns run before generic ones.
DEFAULT_RULES: tuple[RedactionRule, ...] = (
    RedactionRule(
        "private_key",
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
        "[REDACTED_PRIVATE_KEY]",
    ),
    RedactionRule(
        "jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"), "[REDACTED_TOKEN]"
    ),
    RedactionRule("openai_key", re.compile(r"\bsk-(?:proj-|ant-)?[A-Za-z0-9_-]{16,}\b"), "[REDACTED_API_KEY]"),
    RedactionRule("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), "[REDACTED_API_KEY]"),
    RedactionRule(
        "github_token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{20,}\b"), "[REDACTED_API_KEY]"
    ),
    RedactionRule("slack_token", re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}\b"), "[REDACTED_API_KEY]"),
    RedactionRule("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"), "[REDACTED_API_KEY]"),
    RedactionRule("stripe_key", re.compile(r"\b(?:sk|pk|rk)_(?:live|test)_[A-Za-z0-9]{16,}\b"), "[REDACTED_API_KEY]"),
    RedactionRule("bearer_token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}"), "Bearer [REDACTED_TOKEN]"),
    RedactionRule(
        "credential_assignment",
        re.compile(
            r"(?i)\b(password|passwd|pwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret)\b(\s*[:=]\s*)(\"[^\"]+\"|'[^']+'|\S+)"
        ),
        r"\1\2[REDACTED_SECRET]",
    ),
    RedactionRule("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "[REDACTED_EMAIL]"),
    RedactionRule("credit_card", re.compile(r"\b(?:\d[ -]?){12,18}\d\b"), "[REDACTED_CARD]", _luhn_ok),
    RedactionRule("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[REDACTED_SSN]"),
    RedactionRule(
        "phone",
        re.compile(
            r"(?<![\w.])(?:\+\d{1,3}[\s.-]?)?(?:\(\d{2,4}\)[\s.-]?|\d{2,4}[\s.-])\d{3,4}[\s.-]\d{3,4}(?!\w|\.\d)"
        ),
        "[REDACTED_PHONE]",
    ),
    RedactionRule(
        "phone_international",
        re.compile(r"(?<![\w.])\+\d{1,3}[\s.-]?\d{2,5}(?:[\s.-]\d{2,5}){1,3}(?!\w|\.\d)"),
        "[REDACTED_PHONE]",
        lambda m: 8 <= sum(c.isdigit() for c in m) <= 15,
    ),
    RedactionRule("phone_compact", re.compile(r"(?<![\w.])\+\d{10,14}(?!\w|\.\d)"), "[REDACTED_PHONE]"),
    RedactionRule("ipv4", re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])"), "[REDACTED_IP]", _valid_ipv4),
    RedactionRule("ipv6", re.compile(r"(?<![:\w])(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}(?![:\w])"), "[REDACTED_IP]"),
)

DEFAULT_SENSITIVE_FIELDS = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "api_key",
        "apikey",
        "access_token",
        "refresh_token",
        "authorization",
        "auth",
        "cookie",
        "set-cookie",
        "ssn",
        "credit_card",
        "card_number",
        "user_email",
        "email",
        "phone",
        "phone_number",
        "ip",
        "ip_address",
        "client_ip",
    }
)


@dataclass
class RedactionConfig:
    enabled_rules: set[str] | None = None  # None = all rules
    redact_ip_addresses: bool = True
    sensitive_fields: set[str] = field(default_factory=lambda: set(DEFAULT_SENSITIVE_FIELDS))
    custom_patterns: dict[str, str] = field(default_factory=dict)  # name -> regex


@dataclass
class RedactionResult:
    text: str
    counts: Counter[str]


class Redactor:
    def __init__(self, config: RedactionConfig | None = None) -> None:
        self.config = config or RedactionConfig()
        rules = list(DEFAULT_RULES)
        if not self.config.redact_ip_addresses:
            rules = [r for r in rules if r.name not in ("ipv4", "ipv6")]
        if self.config.enabled_rules is not None:
            rules = [r for r in rules if r.name in self.config.enabled_rules]
        for name, pattern in self.config.custom_patterns.items():
            rules.append(RedactionRule(f"custom:{name}", re.compile(pattern), f"[REDACTED_{name.upper()}]"))
        self.rules = rules
        self.sensitive_fields = {f.lower() for f in self.config.sensitive_fields}

    def redact_text(self, text: str | None) -> RedactionResult:
        counts: Counter[str] = Counter()
        if not text:
            return RedactionResult(text or "", counts)
        out = text
        for rule in self.rules:

            def _sub(m: re.Match[str], rule: RedactionRule = rule) -> str:
                if rule.validator and not rule.validator(m.group(0)):
                    return m.group(0)
                counts[rule.name] += 1
                return m.expand(rule.placeholder)

            out = rule.pattern.sub(_sub, out)
        return RedactionResult(out, counts)

    def redact_value(self, value: Any, counts: Counter[str], key: str | None = None) -> Any:
        if key is not None and key.lower() in self.sensitive_fields and value not in (None, "", [], {}):
            counts[f"field:{key.lower()}"] += 1
            return "[REDACTED_FIELD]"
        if isinstance(value, str):
            res = self.redact_text(value)
            counts.update(res.counts)
            return res.text
        if isinstance(value, dict):
            return {k: self.redact_value(v, counts, str(k)) for k, v in value.items()}
        if isinstance(value, list):
            return [self.redact_value(v, counts) for v in value]
        return value


def contains_secret(text: str, redactor: Redactor | None = None) -> bool:
    """True when the default rules would redact something in `text`."""
    r = redactor or Redactor()
    return sum(r.redact_text(text).counts.values()) > 0
