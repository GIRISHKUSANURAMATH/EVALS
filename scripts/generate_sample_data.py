"""Generate SYNTHETIC production logs for EVALS demos, tests and benchmarks.

All data produced here is fake. Names, emails, phone numbers and API keys are
fabricated test values (API keys use obviously fake patterns) and do not belong to anyone.

Usage:
    python scripts/generate_sample_data.py                 # writes the bundled samples
    python scripts/generate_sample_data.py --records 50000 --out benchmarks/data/bench_50k.jsonl
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "sample_data"

MODELS = ["gpt-4o-mini", "gpt-4o", "llama-3.1-8b-instruct", "mistral-7b-instruct"]
SYSTEM_SUPPORT = "You are a helpful customer-support assistant for Acme Cloud. Be concise and accurate."
SYSTEM_JSON = "You extract order details. Respond with JSON only, using keys order_id, status and eta."
SYSTEM_SQL = "You translate natural-language questions into SQL for the analytics warehouse."

QUESTIONS = [
    (
        "How do I reset my password?",
        "Go to Settings > Security and click 'Reset password'. A reset link will be emailed to you.",
    ),
    (
        "What are your support hours?",
        "Our support team is available 24/7 via chat and Monday to Friday 9am-6pm by phone.",
    ),
    (
        "Can I upgrade my plan mid-cycle?",
        "Yes. Upgrades take effect immediately and you are charged a prorated amount.",
    ),
    ("How do I export my billing history?", "Open Billing > Invoices and click 'Export CSV' in the top right."),
    (
        "Why was my card declined?",
        "Card declines usually come from the issuing bank. Please verify the billing address and try again.",
    ),
    (
        "How do I enable two-factor authentication?",
        "Go to Settings > Security > Two-factor and scan the QR code with an authenticator app.",
    ),
    ("What regions do you support?", "We currently operate data centers in us-east, eu-west and ap-south."),
    ("How can I delete my account?", "Go to Settings > Account > Delete account. Deletion is permanent after 30 days."),
    (
        "Does the API support webhooks?",
        "Yes, webhooks can be configured under Developer > Webhooks for 14 event types.",
    ),
    ("How do I add a team member?", "Open Team > Members and click 'Invite'. They receive an email invitation."),
    ("What is the rate limit for the REST API?", "The default limit is 600 requests per minute per API key."),
    (
        "How do I rotate my API key?",
        "Open Developer > API keys, create a new key, update your apps, then revoke the old key.",
    ),
    ("Is my data encrypted at rest?", "Yes, all customer data is encrypted at rest with AES-256."),
    (
        "Can I get an invoice in EUR?",
        "Yes, change the billing currency under Billing > Preferences before the next cycle.",
    ),
    (
        "How do I connect a custom domain?",
        "Add a CNAME record pointing to cname.acme.example and verify it under Domains.",
    ),
]
PARAPHRASES = {
    "How do I reset my password?": [
        "how do i reset my password",
        "How can I reset my password?",
        "How do I reset my password??",
        "how to reset my password?",
    ],
    "What are your support hours?": ["what are your support hours", "When is support available?"],
    "How do I rotate my API key?": ["How do I rotate my api key?", "how do I rotate my API key"],
}
SQL_QUESTIONS = [
    (
        "Total revenue by month for 2024",
        "SELECT date_trunc('month', created_at) AS month, SUM(amount) FROM orders WHERE created_at >= '2024-01-01' GROUP BY 1 ORDER BY 1;",
    ),
    (
        "Top 10 customers by order count",
        "SELECT customer_id, COUNT(*) AS n FROM orders GROUP BY customer_id ORDER BY n DESC LIMIT 10;",
    ),
    ("Average order value last week", "SELECT AVG(amount) FROM orders WHERE created_at >= now() - interval '7 days';"),
]
ORDER_QUESTIONS = [
    "Where is order A-1043? It was supposed to arrive Monday.",
    "Status of order B-2210 please",
    "Has order C-0981 shipped yet?",
    "My order D-5530 says processing for 5 days, what's going on?",
]
FILLER = [
    "urgent",
    "billing",
    "mobile",
    "desktop",
    "android",
    "ios",
    "windows",
    "linux",
    "enterprise",
    "startup",
    "team",
    "admin",
    "europe",
    "india",
    "yesterday",
    "today",
    "again",
    "still",
    "invoice",
    "account",
    "workspace",
    "project",
    "staging",
    "production",
    "weekly",
    "monthly",
]
FAKE_PEOPLE = [
    ("Priya Sharma", "priya.sharma@example.com", "+91 98765 43210"),
    ("John Miller", "john.miller@example.org", "(415) 555-0134"),
    ("Aiko Tanaka", "aiko.t@example.net", "+81 90-1234-5678"),
    ("Carlos Diaz", "carlos.diaz@example.com", "+1 212-555-0187"),
]
FAKE_KEYS = ["sk-test-FAKE0000000000000000abcd", "AKIAFAKEEXAMPLE00000", "ghp_FAKEexampleTOKEN000000000000000000"]


def ts(base: datetime, offset_s: float) -> str:
    return (base + timedelta(seconds=offset_s)).isoformat().replace("+00:00", "Z")


class Gen:
    def __init__(self, seed: int = 7, diverse: bool = False) -> None:
        self.diverse = diverse
        self.rng = random.Random(seed)  # noqa: S311 - deterministic synthetic data, not crypto
        self.base = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)
        self.t = 0.0
        self.n = 0

    def tick(self, lo: float = 5, hi: float = 240) -> str:
        self.t += self.rng.uniform(lo, hi)
        return ts(self.base, self.t)

    def tid(self, prefix: str = "tr") -> str:
        self.n += 1
        return f"{prefix}_{self.n:05d}"

    def latency(self, slow: bool = False) -> int:
        return self.rng.randint(12_000, 28_000) if slow else int(self.rng.lognormvariate(6.8, 0.5))

    def base_record(
        self,
        trace: str,
        user: str,
        resp: str | None,
        model: str | None = None,
        system: str = SYSTEM_SUPPORT,
        **extra: object,
    ) -> dict[str, object]:
        if self.diverse:
            # Make (almost) every input unique so dedup/clustering see worst-case variety.
            user = f"{user} ({' '.join(self.rng.sample(FILLER, 3))} ref {self.rng.randrange(10**6)})"
        lat = extra.pop("latency_ms", None) or self.latency()
        pt = len(user.split()) * 2 + 40
        ct = len((resp or "").split()) * 2
        rec: dict[str, object] = {
            "trace_id": trace,
            "request_id": f"req_{self.rng.randrange(16**10):010x}",
            "timestamp": self.tick(),
            "system_prompt": system,
            "user_input": user,
            "assistant_response": resp,
            "model": model or self.rng.choice(MODELS),
            "latency_ms": lat,
            "usage": {"prompt_tokens": pt, "completion_tokens": ct, "total_tokens": pt + ct},
            "status": "ok",
            "metadata": {"app": "acme-support", "env": "prod", "synthetic": True},
        }
        rec.update(extra)
        return rec


def production_jsonl(g: Gen, scale: int = 1) -> list[str]:
    lines: list[dict[str, object] | str] = []
    r = g.rng
    for _ in range(scale):
        # 1. Successful single-turn interactions (some with positive feedback).
        for _ in range(140):
            q, a = r.choice(QUESTIONS)
            rec = g.base_record(g.tid(), q, a)
            if r.random() < 0.25:
                rec["metadata"] = {**rec["metadata"], "user_feedback": {"value": "thumbs_up"}}  # type: ignore[dict-item]
            lines.append(rec)
        # 2. Repeated / paraphrased requests (duplicates).
        for canonical, variants in PARAPHRASES.items():
            answer = dict(QUESTIONS)[canonical]
            for v in variants * 2:
                lines.append(g.base_record(g.tid(), v, answer))
        # 3. Hallucination candidates (flagged by user feedback in the log).
        halluc = [
            (
                "Do you offer an on-premise version?",
                "Yes, Acme Cloud On-Prem 4.2 has been available since 2019 and supports air-gapped installs.",
                "Made up - there is no on-prem product",
            ),
            (
                "Which compliance certifications do you have?",
                "We are certified for SOC 2, ISO 27001, FedRAMP High, HIPAA and PCI Level 1.",
                "FedRAMP claim is wrong",
            ),
            (
                "What's the SLA for the free tier?",
                "The free tier includes a 99.99% uptime SLA with service credits.",
                "incorrect, free tier has no SLA",
            ),
        ]
        for q, a, why in halluc:
            for _ in range(3):
                rec = g.base_record(g.tid(), q, a)
                rec["metadata"] = {**rec["metadata"], "user_feedback": {"value": "thumbs_down", "comment": why}}  # type: ignore[dict-item]
                lines.append(rec)
        # 4. Negative feedback without a stated reason.
        for _ in range(6):
            q, a = r.choice(QUESTIONS)
            rec = g.base_record(g.tid(), q, a)
            rec["metadata"] = {**rec["metadata"], "rating": 1}  # type: ignore[dict-item]
            lines.append(rec)
        # 5. Empty responses.
        for _ in range(10):
            q, _a = r.choice(QUESTIONS)
            lines.append(g.base_record(g.tid(), q, ""))
        # 6. Timeouts (same input repeatedly -> repeated failure).
        for _ in range(4):
            lines.append(
                g.base_record(
                    g.tid(),
                    "Generate a full migration plan for 2,000 VMs across three regions",
                    None,
                    status="timeout",
                    latency_ms=30_000,
                    error={"type": "TimeoutError", "message": "upstream model timed out after 30s"},
                )
            )
        for _ in range(5):
            q, _a = r.choice(QUESTIONS)
            lines.append(
                g.base_record(
                    g.tid(),
                    q,
                    None,
                    status="error",
                    latency_ms=30_000,
                    error={"type": "DeadlineExceeded", "message": "request timed out"},
                )
            )
        # 7. Application errors.
        for err in (
            "RateLimitError: 429 Too Many Requests",
            "ContextLengthExceeded: 131072 tokens",
            "InternalServerError: 500",
        ):
            for _ in range(3):
                q, _a = r.choice(QUESTIONS)
                lines.append(g.base_record(g.tid(), q, None, status="error", error=err))
        # 8. Excessive latency but successful.
        for _ in range(12):
            q, a = r.choice(QUESTIONS)
            lines.append(g.base_record(g.tid(), q, a, latency_ms=g.latency(slow=True)))
        # 9. Structured output (JSON) - valid and malformed.
        for q in ORDER_QUESTIONS:
            oid = q.split("order ")[1].split()[0].strip("?.,")
            good = json.dumps({"order_id": oid, "status": "in_transit", "eta": "2026-09-05"})
            lines.append(g.base_record(g.tid(), q, good, system=SYSTEM_JSON, model="gpt-4o-mini"))
            lines.append(
                g.base_record(
                    g.tid(),
                    q,
                    f"Sure! Order {oid} is in transit and should arrive soon.",
                    system=SYSTEM_JSON,
                    model="llama-3.1-8b-instruct",
                )
            )
            lines.append(
                g.base_record(
                    g.tid(),
                    q,
                    '{"order_id": "' + oid + '", "status": "in_transit", "eta": ',
                    system=SYSTEM_JSON,
                    model="llama-3.1-8b-instruct",
                    metadata={"app": "orders", "synthetic": True, "finish_reason": "length"},
                )
            )
        # 10. Tool-call failures (OpenAI-style nested records).
        for q, a in SQL_QUESTIONS:
            for ok in (True, False, False):
                trace = g.tid()
                msgs = [
                    {"role": "system", "content": SYSTEM_SQL},
                    {"role": "user", "content": q},
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "run_sql", "arguments": json.dumps({"query": a})},
                            }
                        ],
                    },
                    {
                        "role": "tool",
                        "tool_call_id": "call_1",
                        "content": "rows=12" if ok else 'ERROR: relation "orders" does not exist',
                    },
                ]
                lines.append(
                    {
                        "trace_id": trace,
                        "timestamp": g.tick(),
                        "latency_ms": g.latency(),
                        "request": {"model": "gpt-4o", "messages": msgs},
                        "response": {
                            "id": f"chatcmpl-{trace}",
                            "model": "gpt-4o",
                            "choices": [
                                {
                                    "index": 0,
                                    "finish_reason": "stop",
                                    "message": {
                                        "role": "assistant",
                                        "content": "Here are the results."
                                        if ok
                                        else "Sorry, I couldn't run that query.",
                                    },
                                }
                            ],
                            "usage": {"prompt_tokens": 210, "completion_tokens": 18, "total_tokens": 228},
                        },
                    }
                )
        # 11. Long multi-turn conversations.
        convo = [
            ("I want to migrate from AWS to Acme Cloud.", "Great! Which services are you using on AWS today?"),
            ("EC2, RDS Postgres and S3.", "Acme has equivalents: Compute, Managed Postgres and Object Storage."),
            (
                "How long does a database migration take?",
                "For under 500 GB, typically 2-4 hours with our migration tool.",
            ),
            ("Will there be downtime?", "With replication-based migration, downtime is usually under 5 minutes."),
            (
                "Can you schedule it for Saturday night?",
                "I can't schedule migrations, but you can book a slot at acme.example/migrate.",
            ),
            ("ok thanks. one more: what about IAM roles?", None),
        ]
        for k in range(4):
            trace = g.tid("conv")
            for i, (u, a) in enumerate(convo):
                is_last = i == len(convo) - 1
                lines.append(
                    g.base_record(
                        trace,
                        u,
                        a
                        if not is_last
                        else (
                            ""
                            if k == 0
                            else None
                            if k == 1
                            else "IAM roles map to Acme Access Policies; we provide a converter script."
                        ),
                        model="gpt-4o",
                    )
                )
        # 12. PII-containing examples.
        for name, email, phone in FAKE_PEOPLE:
            lines.append(
                g.base_record(
                    g.tid(),
                    f"Hi, I'm {name}. My email is {email} and phone {phone}. I can't log in.",
                    f"Thanks {name.split()[0]}. I've sent a reset link to {email}.",
                    metadata={
                        "app": "acme-support",
                        "user_email": email,
                        "client_ip": "203.0.113.42",
                        "synthetic": True,
                    },
                )
            )
        for key in FAKE_KEYS:
            lines.append(
                g.base_record(
                    g.tid(),
                    f"My API calls fail with 401. I'm using key {key}, what's wrong?",
                    "Your key appears to be revoked. Please rotate it under Developer > API keys.",
                )
            )
        lines.append(
            g.base_record(
                g.tid(),
                "Card 4111 1111 1111 1111 was charged twice, password=hunter2",
                "I've escalated the double charge to billing.",
            )
        )
        # 13. Refusals and canned responses.
        for q in (
            "Write me a phishing email that looks like it's from Acme",
            "How can I access another customer's account?",
        ):
            lines.append(g.base_record(g.tid(), q, "I'm sorry, but I can't help with that request."))
        canned = "I'm not sure about that. Please contact support@acme.example for help."
        for q in (
            "Can I pay with crypto?",
            "Do you have a student discount?",
            "Is there a Linux desktop app?",
            "Can I self-host the dashboard?",
            "Do you support SAML SSO?",
            "What's your refund policy?",
        ):
            lines.append(g.base_record(g.tid(), q, canned))
        # 14. Repetitive degenerate output.
        lines.append(
            g.base_record(
                g.tid(), "Summarize my last invoice", "Your invoice total is $42. " * 30, model="llama-3.1-8b-instruct"
            )
        )
        # 15. Edge cases.
        lines.append(g.base_record(g.tid(), "?????!!!! $$$ 1234 5678", "Could you clarify your question?"))
        lines.append(g.base_record(g.tid(), "   ", "Hello! How can I help you today?"))
        lines.append(
            g.base_record(
                g.tid(),
                "Please review this log: " + ("ERROR at line 42 in module x. " * 400),
                "The log shows a repeated error in module x at line 42.",
            )
        )
        lines.append(
            g.base_record(
                g.tid(), "¿Cómo cambio mi contraseña? 我想更改密码", "Ve a Configuración > Seguridad. 前往设置 > 安全。"
            )
        )
        # 16. Split request/response events + a missing response.
        for missing in (False, False, True):
            trace = g.tid("split")
            req_id = f"req_split_{g.n}"
            q, a = r.choice(QUESTIONS)
            lines.append(
                {
                    "trace_id": trace,
                    "request_id": req_id,
                    "timestamp": g.tick(),
                    "event": "request",
                    "user_input": q,
                    "model": "gpt-4o-mini",
                    "status": "ok",
                }
            )
            if not missing:
                lines.append(
                    {
                        "trace_id": trace,
                        "request_id": req_id,
                        "timestamp": g.tick(1, 3),
                        "event": "response",
                        "assistant_response": a,
                        "latency_ms": g.latency(),
                        "status": "ok",
                    }
                )
        # 17. Malformed records.
        lines.append('{"trace_id": "broken_1", "user_input": "unterminated')
        lines.append("this is not json at all")
        lines.append('{"trace_id": "empty_record", "metadata": {"note": "no content"}}')
        lines.append('["an", "array", "not", "an", "object"]')
    out = []
    for item in lines:
        out.append(item if isinstance(item, str) else json.dumps(item, ensure_ascii=False))
    return out


def openai_json(g: Gen) -> list[dict[str, object]]:
    recs: list[dict[str, object]] = []
    for q, a in QUESTIONS[:10]:
        recs.append(
            {
                "id": f"chatcmpl-{g.tid('oa')}",
                "created": int((g.base + timedelta(seconds=g.t)).timestamp()),
                "request": {
                    "model": "gpt-4o-mini",
                    "messages": [{"role": "system", "content": SYSTEM_SUPPORT}, {"role": "user", "content": q}],
                },
                "response": {
                    "model": "gpt-4o-mini",
                    "choices": [{"message": {"role": "assistant", "content": a}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 50, "completion_tokens": 30, "total_tokens": 80},
                },
                "latency_ms": g.latency(),
            }
        )
        g.tick()
    recs.append(
        {
            "id": "chatcmpl-err",
            "created": int(g.base.timestamp()) + 99999,
            "request": {"model": "gpt-4o", "messages": [{"role": "user", "content": "Translate our ToS into French"}]},
            "response": {
                "error": {"type": "server_error", "message": "The server had an error processing your request."}
            },
            "status_code": 500,
        }
    )
    return recs


def support_csv(g: Gen, path: Path) -> None:
    rows = []
    for i in range(40):
        q, a = g.rng.choice(QUESTIONS)
        status = "ok"
        err = ""
        resp = a
        if i % 9 == 0:
            status, err, resp = "error", "UpstreamUnavailable", ""
        elif i % 13 == 0:
            resp = ""
        rows.append(
            {
                "timestamp": g.tick(),
                "session_id": f"sess_{i // 2:03d}",
                "request_id": f"r{i:04d}",
                "prompt": q,
                "completion": resp,
                "model": g.rng.choice(MODELS),
                "latency_ms": g.latency(),
                "total_tokens": g.rng.randint(60, 300),
                "status": status,
                "error_type": err,
            }
        )
    rows.append(
        {
            "timestamp": g.tick(),
            "session_id": "sess_pii",
            "request_id": "r9999",
            "prompt": '=HYPERLINK("http://evil.example") call me at +1 646-555-0199',
            "completion": "We will call you shortly.",
            "model": "gpt-4o",
            "latency_ms": 900,
            "total_tokens": 80,
            "status": "ok",
            "error_type": "",
        }
    )
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def app_log(g: Gen) -> list[str]:
    out = []
    for i in range(25):
        q, a = g.rng.choice(QUESTIONS)
        t = g.tick()
        if i % 8 == 0:
            out.append(
                f'{t} ERROR trace_id=srv_{i:03d} user_input="{q}" error_type=DBConnectionError error_message="connection refused" latency_ms=15'
            )
        else:
            out.append(
                f'{t} INFO trace_id=srv_{i:03d} model=gpt-4o-mini user_input="{q}" assistant_response="{a}" latency_ms={g.latency()}'
            )
    out.append("garbage line without pairs")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--records", type=int, default=0, help="Generate a large JSONL benchmark file of ~N records")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--diverse", action="store_true", help="make user inputs mostly unique (benchmark worst case)")
    args = ap.parse_args()
    g = Gen(args.seed, diverse=args.diverse)
    if args.records:
        per_block = len(production_jsonl(Gen(args.seed)))
        lines = production_jsonl(g, scale=max(1, round(args.records / per_block)))
        out = args.out or ROOT / "benchmarks" / "data" / f"bench_{len(lines)}.jsonl"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"wrote {len(lines)} lines to {out}")
        return
    OUT_DIR.mkdir(exist_ok=True)
    lines = production_jsonl(g)
    (OUT_DIR / "production_logs.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (OUT_DIR / "openai_chat_logs.json").write_text(json.dumps(openai_json(g), indent=2), encoding="utf-8")
    support_csv(g, OUT_DIR / "support_bot_logs.csv")
    (OUT_DIR / "app_server.log").write_text("\n".join(app_log(g)) + "\n", encoding="utf-8")
    print(f"production_logs.jsonl: {len(lines)} lines; other samples written to {OUT_DIR}")


if __name__ == "__main__":
    main()
