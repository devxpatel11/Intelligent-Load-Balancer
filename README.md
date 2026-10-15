# Intelligent Network Load Balancer

NetBalance is an educational application-aware TCP load balancer built with Python 3.12, `asyncio` streams, FastAPI, and a local vanilla-JavaScript dashboard. It routes one newline-delimited JSON request per connection across three independent backends using Round Robin (`rr`), Least Connections (`lc`), or Smooth Weighted Round Robin (`swrr`).

## Verified status

A1-A5 and B1-B5 are implemented and integrated. The current suite has 90 passing tests, including real loopback backend/proxy traffic, 30-request RR distribution, outage/recovery, all-down, timeout, overload, protocol, accounting, cleanup, dashboard/API, benchmark metadata, analyzer reconciliation, and experiment aggregation paths.

Committed B3 evidence demonstrates RR `10:10:10`, SWRR `15:9:6` at weights `5:3:2`, and bounded failures followed by backend recovery. B4 includes a traceable 30/30-success dry run. B5 adds 36 measured runs with raw/config/environment/trace/proxy evidence, aggregates, a comparison chart, and an evidence-backed report.

## Architecture and contracts

```text
workload/benchmark -- TCP 127.0.0.1:9000 --> proxy -- TCP --> s1 :9101
browser ---------- HTTP 127.0.0.1:8000 -----+-----------> s2 :9102
                                                         `-> s3 :9103
```

The service runs with exactly one Uvicorn worker and no auto-reload. Initial `unknown` and `unhealthy` backends are ineligible; health probes bypass work capacity; requests are never automatically replayed.

The frozen interfaces are [TCP protocol](docs/protocol.md), [components/configuration/API](docs/contracts.md), and [metrics](docs/metrics.md). The dashboard reports application request flow and application failures—not packet capture, packet loss, CPU, memory, or bandwidth utilization.

## Setup

Python 3.12 and Git are required. Installation needs package-index access; runtime uses no cloud service, database, Node, or CDN.

Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python -m pip install --no-deps -e .
python scripts/verify.py
```

POSIX shell:

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pip install --no-deps -e .
python scripts/verify.py
```

The pinned environment was verified on Windows. The POSIX commands are exercised by the Ubuntu CI workflow.

## Run the live system

Start the three backends and the single-worker service with one owned-process launcher:

```text
python -m netbalance.demo --profile uniform
```

Open `http://127.0.0.1:8000/`. Press `Ctrl+C` in the launcher terminal to stop only its child processes. The other profiles are `slow-server` and `capacity`.

Useful HTTP endpoints:

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Service readiness and backend health |
| GET | `/api/metrics` | Immutable counters, latencies, backend state, recent events |
| GET | `/api/config` | Current policy, weights, deadlines, and revision |
| POST | `/api/algorithm` | Apply `{"algorithm":"rr"}`, `lc`, or `swrr` |
| POST | `/api/weights` | Apply all backend weights, for example `{"weights":{"s1":5,"s2":3,"s3":2}}` |
| POST | `/api/reset` | Reset idle metrics with `{}`; active work returns `409` |

Run a basic workload while the demo is active:

```text
python -m netbalance.workload --count 30 --concurrency 6 --output results/manual.csv --policy rr --scenario manual
```

## Benchmark and analyze

The benchmark requires a live proxy and HTTP API. It saves raw per-attempt CSV plus metadata containing the commit, environment, arguments, live configuration, measured duration, and summary:

```text
python -m netbalance.benchmark --count 300 --concurrency 30 --policy rr --scenario uniform --output results/uniform_rr.csv
python -m netbalance.analyze results/uniform_rr.csv --output results/uniform_rr_summary.json
```

Use `--host`/`--port` for the TCP proxy and `--http-host`/`--http-port` for the API when not using default ports. The analyzer rejects malformed rows and count mismatches and uses the frozen successful-throughput and nearest-rank percentile definitions.

## Verification

```text
python scripts/verify.py
python -m pytest tests/unit -q
python -m pytest tests/integration -q
python -m pytest -q
python -m pip check
```

Integration tests use real loopback sockets, ephemeral ports, finite readiness/deadline polling, and cleanup limited to owned processes. Timing values are evidence, not deterministic pass thresholds.

## Evidence

- `results/demo_rr_30.csv`, `demo_swrr_30.csv`, `demo_outage_recovery.csv`, and `demo_outage_meta.json`: B3 live behavior evidence.
- `results/dry_run.csv`, `dry_run.csv.meta.json`, and `dry_run_summary.json`: B4 benchmark/analyzer dry run.
- `results/experiments/`: B5's 36-run controlled matrix, per-run evidence, aggregate table, and comparison chart.
- `docs/report.md`: implementation description, measured results, interpretation, and limitations.
- `docs/readme-notes/`: task commits, exact commands/results, acceptance checks, limitations, and next-task readiness.
- `docs/experiments.md`: controlled B5 plan; planned claims remain separate from measured results.

## Collaboration and repository policy

Member A owns the proxy/service/configuration/API paths and this README. Member B owns backends, workloads, demo/benchmark/analyzer, web assets, and generated evidence. See [AGENTS.md](AGENTS.md), [CONTRIBUTING.md](CONTRIBUTING.md), and [repository settings](docs/repository-settings.md) before changing code.

Changes use task branches and isolated worktrees, cross-review, successful required checks, and sequential merges. Frozen contract changes require a dedicated approved pull request.

## Repository map

```text
configs/                 Frozen default runtime configuration
docs/                    Contracts, plans, handoffs, and report
results/                 Traceable generated evidence
scripts/                 Verification and live evidence helpers
src/netbalance/          Service, proxy, backend, workload, and analysis code
tests/unit/              Parsing, selection, accounting, UI, and tool tests
tests/integration/       Real loopback and owned-process tests
web/                     Offline dashboard assets
```
