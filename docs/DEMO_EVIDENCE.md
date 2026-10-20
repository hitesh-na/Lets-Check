# Verified Windows demo

Recorded verification from 2026-10-20 uses Python 3.11.7, Docker Redis 7.4,
FastAPI, and two separate Python worker processes on Windows. The results
below are supported by the terminal summary and saved batch report.

## Automated tests

Command:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Observed Windows summary:

```text
58 passed, 1 warning in 1.14s
```

The warning is the known Starlette TestClient HTTPX deprecation. Automated
tests mock Redis and outgoing HTTP; the public website is not needed by pytest.

## Manual 20-job batch

Run the API and workers named `worker-1` and `worker-2`, with Redis running.
In a fourth project-root PowerShell terminal:

```powershell
.\.venv\Scripts\python.exe .\scripts\demo_20_jobs.py
```

Recorded terminal output:

```text
Submitted 20 jobs. Waiting for completion...
Completed: 20/20
worker-1: 10 jobs
worker-2: 10 jobs
HTTP 200: 20 jobs
PASS: All 20 jobs completed and both expected workers contributed.
```

The helper reported a saved file named
`demo-20261020T043317Z-2194b0c4.json` under the local `demo-results/` folder.
Inspection of that JSON confirmed 20 unique submitted job IDs, a matching set
of 20 completed results, the reported worker counts, HTTP 200 throughout,
one attempt per check, and ordered UTC submission/start/finish timestamps.
Keep the original report for the full per-job details.

Both named workers handled jobs; their equal counts were observed, not forced.
All 20 checks returned HTTP 200. This demonstrates shared-queue processing
across two processes on one computer, without a claim about speedup,
throughput, multi-machine deployment, or future website availability.

## Completed-result expiry

A separate Windows Redis TTL query for a completed job returned **86315**
seconds, confirming an expiry just under 24 hours. The configured duration is
86400 seconds from completion. This was a TTL inspection, not a 24-hour wait.

## Additional development verification

Controlled checks used real local Redis 6.2.14, the API, and separate workers,
with HTTP mocked where failure scenarios were needed. They verified two
timeouts stopping after two attempts, a successful retry, no retry for HTTP
503, result expiry, and acknowledgment after storage. The batch helper also
reported failure when a worker was missing, jobs exceeded its completion
deadline, or the API was unavailable. Those fixtures are not public website
health or performance measurements.
