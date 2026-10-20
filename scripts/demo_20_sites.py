"""Submit a manual 20-job demo and record whether both named workers contributed."""

import argparse
from collections import Counter
from datetime import UTC, datetime
import json
from pathlib import Path
import time
from uuid import UUID, uuid4
import os
import httpx

BATCH_SIZE = 20
EXPECTED_WORKERS = {"worker-1", "worker-2"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--wait-seconds", type=int, default=180)
    parser.add_argument(
        "--output-dir", type=Path,
        default=Path(__file__).resolve().parent.parent / "demo-results",
    )
    args = parser.parse_args()
    if args.wait_seconds < 1:
        parser.error("--wait-seconds must be positive")

    started_at = datetime.now(UTC)
    job_ids: list[str] = []
    results: dict[str, dict] = {}
    failure = ""
    interrupted = False
    try:
        # The demo talks to the local API directly, without environment proxies.
        with httpx.Client(base_url=args.api_url, timeout=10, trust_env=False) as api:
            for host in os.environ["ALLOWED_HOSTS"].split(","):
                response = api.post("/checks", json={"url": f"https://{host.strip()}/"})
                response.raise_for_status()
                accepted = response.json()
                if response.status_code != 202 or accepted.get("status") != "queued":
                    raise RuntimeError("POST /checks did not return 202 with status queued")
                job_id = str(UUID(accepted.get("job_id", "")))
                if job_id in job_ids:
                    raise RuntimeError("API returned a duplicate job ID")
                job_ids.append(job_id)

            print(f"Submitted {len(job_ids)} jobs. Waiting for completion...", flush=True)
            deadline = time.monotonic() + args.wait_seconds
            pending = set(job_ids)
            while pending and time.monotonic() < deadline:
                for job_id in sorted(pending):
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    response = api.get(f"/checks/{job_id}", timeout=min(10, remaining))
                    response.raise_for_status()
                    result = response.json()
                    if result.get("job_id") != job_id or result.get("status") not in {
                        "queued", "running", "completed",
                    }:
                        raise RuntimeError("GET /checks returned an unexpected job or state")
                    results[job_id] = result
                    if result["status"] == "completed":
                        pending.remove(job_id)
                if pending:
                    time.sleep(max(0, min(0.5, deadline - time.monotonic())))
            if pending:
                failure = (
                    f"{len(pending)} jobs did not complete within {args.wait_seconds} seconds. "
                    "Check the API and worker terminals."
                )
    except KeyboardInterrupt:
        failure = "Demo interrupted. Submitted jobs may continue in the workers."
        interrupted = True
    except (httpx.HTTPError, ValueError, RuntimeError, AttributeError) as error:
        failure = f"{type(error).__name__}: {error}"

    completed = [result for result in results.values() if result["status"] == "completed"]
    worker_counts = Counter(result.get("worker_id") or "(missing)" for result in completed)
    missing_workers = EXPECTED_WORKERS - worker_counts.keys()
    if not failure and missing_workers:
        failure = "No completed jobs from: " + ", ".join(sorted(missing_workers))
    passed = not failure and len(completed) == BATCH_SIZE
    http_counts = Counter(
        str(result["http_status"]) if result.get("http_status") is not None else "no_response"
        for result in completed
    )
    report = {
        "api_url": args.api_url,
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "passed": passed,
        "detail": failure or "All 20 jobs completed and both expected workers contributed.",
        "jobs_submitted": len(job_ids),
        "jobs_completed": len(completed),
        "worker_counts": dict(sorted(worker_counts.items())),
        "http_status_counts": dict(sorted(http_counts.items())),
        "submitted_job_ids": job_ids,
        "results": [results[job_id] for job_id in job_ids if job_id in results],
    }
    output = args.output_dir.resolve() / (
        f"demo-{started_at.strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}.json"
    )
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    except OSError as error:
        print(f"Could not save the demo report: {error}")
        return 1

    print(f"Completed: {len(completed)}/{BATCH_SIZE}")
    for worker_id, count in sorted(worker_counts.items()):
        print(f"{worker_id}: {count} jobs")
    for status_code, count in sorted(http_counts.items()):
        print(f"HTTP {status_code}: {count} jobs")
    print(("PASS: " if passed else "FAIL: ") + report["detail"])
    print(f"Report: {output}")
    return 130 if interrupted else (0 if passed else 1)


if __name__ == "__main__":
    raise SystemExit(main())
