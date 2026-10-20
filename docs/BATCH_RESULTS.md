# Multi-website batch verification

Live checks were run on Windows on 2026-10-20 using Redis, the FastAPI
application, and two independent worker processes on one computer.

## Observed results

| Metric | 20 sites | 200 sites: default header | 200 sites: browser header |
| --- | ---: | ---: | ---: |
| Completed jobs | 20 | 200 | 200 |
| HTTP 200 | 16 | 113 | 113 |
| Other 2xx responses | 0 | 0 | 2 |
| Redirect responses | 3 | 37 | 35 |
| HTTP 403 | 1 | 39 | 40 |
| Other HTTP errors | 0 | 4 | 4 |
| No HTTP response | 0 | 7 | 6 |
| Healthy under current rules | 19 | 150 | 150 |
| Jobs handled by worker-1 | 9 | 113 | 94 |
| Jobs handled by worker-2 | 11 | 87 | 106 |

The default-header 200-site batch started at
2026-10-20T17:41:42.530747+00:00 and finished at
2026-10-20T17:42:33.484484+00:00: 50.95 seconds elapsed.
This includes submission and polling overhead.

All 20 distinct-site checks completed on their first attempt. The two
200-site runs both reported PASS, with all jobs completed and both workers
contributing. Worker counts do not need to be equal.

These live batches are separate from the mocked automated test suite.
The previously recorded 58-test result is documented in the original
demo evidence; these batch runs do not establish a new unit-test result.

## Interpreting the outcomes

A completed job means the check finished, including an unsuccessful
HTTP or network outcome. A batch PASS does not mean every site was healthy.

The checker marks HTTP 200-399 as healthy. Redirects are recorded without
following their destinations. HTTP 403 means access was denied; its status
alone does not establish that the website was down or identify the cause.

The worker was configured with a browser-style User-Agent for the second
200-site run. The aggregate healthy count remained 150/200 and the 403 count
changed from 39 to 40. These runs show no aggregate improvement from that
change and do not establish the cause of individual response differences.

The User-Agent is configured in run_worker() in app/worker.py. Restart both
workers after changing it. A browser-style header does not turn HTTPX into
a browser or guarantee access through a site's protection systems.

## Reproduce a batch

Use the project README to start Redis, the API, and workers named worker-1
and worker-2. Before starting the API and workers, load the same target
list in all four PowerShell terminals:

```powershell
$env:ALLOWED_HOSTS = (Get-Content .\sites_200.txt) -join ","
```

Restart existing API and worker processes after changing their allowlists.
In the fourth terminal, run:

```powershell
.\.venv\Scripts\python.exe .\scripts\demo_200_sites.py --wait-seconds 1800 --output-dir .\demo-results\200-sites
```

For the 20-site batch, load sites_20.txt in all four terminals instead,
restart the API and workers, and run:

```powershell
.\.venv\Scripts\python.exe .\scripts\demo_20_sites.py --output-dir .\demo-results\20-sites
```

Each helper expects its stated number of hosts. The 200-site run allows
up to 1800 seconds for completion; it finishes earlier when all jobs finish.
Reload the generated JSON file before comparing results in PowerShell.

## Retained evidence

- [Default-header 200-site report](results/200-sites-default-header.json)
- [Browser-header 200-site report](results/200-sites-browser-header.json)
- [Original demo and automated-test evidence](DEMO_EVIDENCE.md)

Other generated reports remain under demo-results/, which is excluded
from Git. These measurements demonstrate local batch processing with two
worker processes. Pending-job recovery after a worker crash remains
unimplemented.
