# Security

## Threat model

EVALS processes production logs that may contain personal data and credentials. The main
risks are (1) sensitive data reaching storage, exports or logs, (2) malicious uploads, and
(3) unauthorised destructive operations. EVALS is designed for local or trusted-network use;
it does **not** implement user accounts.

## Controls

| Risk | Control | Where |
| --- | --- | --- |
| PII / secrets in stored data | Redaction runs before persistence on all text fields and metadata strings | `privacy/` |
| Raw data retained | Unredacted text is not kept unless `EVALS_PRESERVE_RAW_CONTENT=true`; never returned by the API or exports | `privacy/pipeline.py`, exporters |
| Uploaded content in logs | Only counts, ids and timings are logged; unhandled errors log the exception type only | `core/logging.py`, `main.py` |
| Input echoed in errors | 422 responses include field location and message, never submitted values | `main.py` |
| Oversized / hostile files | size limit, extension allow-list, NUL-byte (binary) rejection, strict UTF-8, record-count cap | `ingestion/validation.py`, `parsers.py` |
| Deeply nested JSON (stack exhaustion) | records nested more than 64 levels are reported as malformed; a document too deep for the JSON parser is rejected with 422 instead of crashing | `ingestion/parsers.py` |
| Path traversal | uploads are never written to disk by name; filenames are reduced to a safe basename; sample names come from a fixed allow-list; ids are UUID-validated | `core/security.py`, routes |
| SQL injection | SQLAlchemy bound parameters everywhere, including search | services |
| Destructive operations | reset, dataset delete and settings changes require `X-Admin-Key`, compared in constant time; **disabled (403) when no key is configured** | `core/security.py` |
| CSV formula injection | cells starting with `= + - @ \t \r` are prefixed with `'` | `evaluation/exporters.py` |
| Malformed exports | every exported record validated against a Pydantic schema, and text fields get a final redaction pass | `evaluation/exporters.py`, `services/datasets.py` |
| Cross-site scripting | React escapes all rendered text; no `dangerouslySetInnerHTML`, `innerHTML` or `eval` in the frontend | `frontend/src` |
| Cross-origin abuse | CORS limited to configured origins, methods and headers; no credentials allowed | `main.py` |
| Debug mode in production | no FastAPI debug flag; `--reload` is only used in the documented local dev command, not in Docker | `main.py`, `docker/` |
| Secrets in the repository | `.env` git-ignored; `.env.example` contains no values; sample keys are obviously fake | `.gitignore` |

## Known gaps

- No authentication or per-user authorisation for read, upload and review endpoints.
- Regex PII detection does not find names, addresses or free-form identifiers.
- Custom regex patterns are validated and length-limited, but a pathological pattern could
  still be slow (Python's `re` has no timeout). Only admins can add patterns.
- Processing is synchronous; many large concurrent uploads could exhaust a small server.
- The SQLite file is not encrypted at rest.

## Dependency audit

Recorded 2026-11-06 on the pinned dependencies.

| Ecosystem | Command | Result |
| --- | --- | --- |
| Python runtime | `pip-audit -r backend/requirements.txt` | no known vulnerabilities |
| Python dev | `pip-audit -r backend/requirements-dev.txt` | no known vulnerabilities |
| Frontend production | `npm audit --omit=dev` | 0 vulnerabilities |
| Frontend all | `npm audit` | **7 moderate (development only)** |

The 7 moderate findings are a single advisory, GHSA-g3hv-75wg-m249 (`minimatch` < 11.0.1,
denial of service via glob-pattern amplification), reached through
`typescript-eslint` → `@typescript-eslint/parser` → `@typescript-eslint/typescript-estree` →
`minimatch` 9.0.9; npm reports each package in that chain separately. It only runs inside
ESLint on patterns from the project's own config, not on user input, and none of it ships in
the built app. Upgrading does not help today (typescript-eslint 8.72.1 still depends on a
vulnerable `minimatch` 10.x), and npm's suggested "fix" is a downgrade to typescript-eslint
7.x, which was deliberately not applied.

### npm install scripts

Three dev dependencies declare install scripts: `esbuild` and `@tailwindcss/oxide`
(`postinstall`), and `fsevents` (macOS only). The first two only check that their
platform-specific binary package (for example `@esbuild/win32-x64`,
`@tailwindcss/oxide-win32-x64-msvc`) was installed, and download it from
`registry.npmjs.org` if it was not. Those binary packages are already pinned in
`package-lock.json`, and a clean `npm ci --ignore-scripts` followed by `npm test` and
`npm run build` succeeded in the verification environment. Running with `--ignore-scripts`
is therefore an option if you prefer not to run third-party install scripts. That has not
yet been verified on Windows.

## Reporting

If you find a vulnerability, please open a private security advisory on the repository
rather than a public issue.
