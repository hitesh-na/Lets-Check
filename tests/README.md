# Tests

From the project root on Windows:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

The tests mock Redis and outgoing HTTP. They require neither a running Redis
server nor a public internet connection. Tests cover URL validation, actual
stream-publication calls, queue/storage failure responses, job lookups, streamed
HTTP outcomes, no followed redirects, save-before-ack ordering, and continuing
after a malformed message. Completed storage includes a 24-hour expiry before
acknowledgment; the running state is saved without an expiry.

Retry tests cover connection errors and all HTTPX timeout types stopping after
two attempts, recovery on the second attempt, total latency across attempts,
and sanitized terminal errors/retry logs. HTTP 400, 404, 429, 500, and 503 are
not retried. Other request errors such as ReadError are also terminal. The
20-job real-process demo is a separate integration gate.

Latest development result: **58 passed, 1 warning** on Linux/Python 3.12.
Verified Windows/Python 3.11.7 result: **58 passed, 1 warning in 1.14s**.

For the manual 20-job demo, start the API, Redis, and workers named `worker-1`
and `worker-2`, then run in a fourth project-root terminal:

```powershell
.\.venv\Scripts\python.exe .\scripts\demo_20_jobs.py
```

This sends real jobs to the running API and uses the workers' actual HTTP
outcomes. Reports go to `demo-results/`. A pass requires all 20 jobs completed
and both expected worker IDs present. The helper has been verified with real
Redis/API/two-worker processes and mocked outbound HTTP in development. The
actual Windows batch also passed: 20/20 completed, worker-1 handled 10,
worker-2 handled 10, and all 20 returned HTTP 200. Its terminal summary is
recorded in [docs/DEMO_EVIDENCE.md](../docs/DEMO_EVIDENCE.md). The manual demo
is not included in `pytest`.

The installed Starlette TestClient emits a deprecation warning about HTTPX;
it does not fail the test suite. See [the demo record](../docs/DEMO_EVIDENCE.md)
for recorded integration results.
