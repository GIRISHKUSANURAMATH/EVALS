"""Reproducible EVALS benchmark.

Generates synthetic JSONL logs of several sizes (scripts/generate_sample_data.py) and times
each pipeline stage in isolation, then times the full DB-backed pipeline plus dataset
generation. Results are printed and written to benchmarks/results/<hostname>.json.

Usage (from the project root, with the backend venv active):
    python benchmarks/run_benchmark.py                 # sizes 1000, 5000, 20000
    python benchmarks/run_benchmark.py --sizes 1000 50000
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import socket
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import psutil  # noqa: E402


def _rss_mb() -> float:
    return psutil.Process().memory_info().rss / 1024 / 1024


def _timed(fn):  # type: ignore[no-untyped-def]
    start = time.perf_counter()
    out = fn()
    return out, (time.perf_counter() - start) * 1000


def hardware() -> dict[str, object]:
    freq = psutil.cpu_freq()
    return {
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "processor": platform.processor() or platform.machine(),
        "logical_cpus": psutil.cpu_count(logical=True),
        "physical_cpus": psutil.cpu_count(logical=False),
        "cpu_mhz": round(freq.max or freq.current) if freq else None,
        "ram_gb": round(psutil.virtual_memory().total / 1024**3, 1),
    }


def bench_size(target: int, data_dir: Path, diverse: bool) -> dict[str, object]:
    path = data_dir / f"bench_{target}{'_diverse' if diverse else ''}.jsonl"
    if not path.exists():
        cmd = [
            sys.executable,
            str(ROOT / "scripts" / "generate_sample_data.py"),
            "--records",
            str(target),
            "--out",
            str(path),
        ]
        subprocess.run(cmd + (["--diverse"] if diverse else []), check=True, capture_output=True)  # noqa: S603 - fixed local script
    text = path.read_text(encoding="utf-8")
    content = text.encode()

    from app.ingestion.parsers import parse_content
    from app.privacy.pipeline import redact_record
    from app.privacy.redactor import Redactor
    from app.processing.clustering import ClusterItem, cluster_items
    from app.processing.dedup import DedupItem, deduplicate
    from app.processing.failures import detect_failures
    from app.processing.reconstruction import reconstruct_traces

    rss0 = _rss_mb()
    parsed, t_parse = _timed(lambda: parse_content(text, "jsonl", limit=10_000_000))
    redactor = Redactor()
    _, t_redact = _timed(lambda: [redact_record(r, redactor) for r in parsed.records])
    traces, t_recon = _timed(lambda: reconstruct_traces(parsed.records))
    _, t_fail = _timed(lambda: detect_failures(traces))
    items = [DedupItem(t.trace_key, t.focus().user_input or "") for t in traces]
    (dedup, backend), t_dedup = _timed(lambda: deduplicate(items))
    reps = [t for t in traces if not dedup[t.trace_key].duplicate_of]
    _, t_cluster = _timed(lambda: cluster_items([ClusterItem(t.trace_key, t.focus().user_input or "") for t in reps]))
    rss_stages = _rss_mb()

    # Full pipeline through the service layer into a fresh SQLite database.
    with tempfile.TemporaryDirectory() as tmp:
        from app.core.config import get_settings
        from app.database import session as db_session
        from app.evaluation.generator import GenerationConfig
        from app.services.datasets import ensure_builtin_categories, generate_dataset
        from app.services.pipeline import process_upload

        get_settings().max_upload_mb = 1024
        url = f"sqlite:///{Path(tmp, 'bench.db').as_posix()}"
        db_session.configure_engine(url)
        db_session.run_migrations(url)
        with db_session.SessionLocal() as db:
            ensure_builtin_categories(db)
            job, t_full = _timed(lambda: process_upload(db, path.name, content))
            ds, t_gen = _timed(lambda: generate_dataset(db, "bench", "", None, GenerationConfig(max_examples=100_000)))
            n_examples = len(ds.examples)
        db_session.engine.dispose()
    rss_end = _rss_mb()

    lines = parsed.total_lines
    return {
        "variant": "diverse" if diverse else "templated",
        "records": lines,
        "file_mb": round(len(content) / 1024 / 1024, 2),
        "traces": len(traces),
        "unique_traces": len(reps),
        "examples_generated": n_examples,
        "similarity_backend": backend,
        "stage_ms": {
            "parse_normalize": round(t_parse, 1),
            "redaction": round(t_redact, 1),
            "reconstruction": round(t_recon, 1),
            "failure_detection": round(t_fail, 1),
            "deduplication": round(t_dedup, 1),
            "clustering": round(t_cluster, 1),
        },
        "full_pipeline_ms": round(t_full, 1),
        "dataset_generation_ms": round(t_gen, 1),
        "ingestion_throughput_records_per_s": round(lines / (t_full / 1000), 1),
        "parse_throughput_records_per_s": round(lines / (t_parse / 1000), 1),
        "rss_mb": {"start": round(rss0, 1), "after_stages": round(rss_stages, 1), "end": round(rss_end, 1)},
        "job_stage_timings_ms": job.stats.get("stage_timings_ms"),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", type=int, nargs="+", default=[1000, 5000, 20000])
    ap.add_argument(
        "--diverse-sizes",
        type=int,
        nargs="*",
        default=[1000, 5000, 10000],
        help="sizes to run with mostly-unique inputs (worst case for dedup/clustering)",
    )
    args = ap.parse_args()
    os.environ.setdefault("EVALS_DATABASE_URL", "sqlite:///:memory:")
    data_dir = ROOT / "benchmarks" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    report = {"generated_at": datetime.now(UTC).isoformat(), "hardware": hardware(), "runs": []}
    plan = [(s, False) for s in args.sizes] + [(s, True) for s in args.diverse_sizes]
    for size, diverse in plan:
        print(f"benchmarking ~{size} records ({'diverse' if diverse else 'templated'}) ...", flush=True)
        run = bench_size(size, data_dir, diverse)
        report["runs"].append(run)  # type: ignore[union-attr]
        print(json.dumps(run, indent=2))
    out_dir = ROOT / "benchmarks" / "results"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"{socket.gethostname()}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
