# Intelligent Network Load Balancer with Dynamic Traffic Routing

Educational application-aware TCP load balancer with simulated backend workloads. The finished system will route one newline-delimited JSON request per TCP connection across three independent backend processes and compare Round Robin (`rr`), Least Connections (`lc`), and Smooth Weighted Round Robin (`swrr`).

## Project status

**Current verified milestone: A4 integration, fault, and accounting coverage; G3 is complete.** C0, A1-A4, and B1-B3 are implemented. The package provides strict JSON-line framing and validation, RR/LC/SWRR selectors, atomic backend reservation accounting, metrics, a real asyncio TCP proxy, automatic backend health probing, FastAPI lifecycle and controls, runnable backends, a workload client, a portable demo launcher, and an offline dashboard with live controls.

The 79-test automated suite covers real loopback sockets and subprocesses, three-backend end-to-end traffic, health outage/recovery, all-down and timeout faults, control validation, busy reset, exclusive port ownership and prompt cleanup, workload bounds and response validation, safe dashboard rendering, proxy failure paths, accounting invariants, and API lifecycle behavior.

## Team and ownership

| Member | Exclusive implementation area | Shared responsibility |
| --- | --- | --- |
| Member A | Protocol, selectors, registry, metrics, proxy, service, configuration, API tests, `README.md`, `AGENTS.md` | Review B changes; daily integration; architecture explanation |
| Member B | Backend, workload, benchmark, analyzer, demo launcher, web assets, experiment evidence, report drafts, UI/generator tests | Review A changes; demonstration; result interpretation |

Replace the member labels with names and registration details in `docs/contributions.md` before submission.

## Frozen design

- Python 3.12 and real `asyncio` TCP streams.
- Proxy TCP endpoint: `127.0.0.1:9000`.
- Local HTTP API/dashboard: `127.0.0.1:8000`, one Uvicorn worker.
- Backends: `s1`/`s2`/`s3` on ports `9101`/`9102`/`9103`.
- One UTF-8 JSON line request and response per connection; maximum complete frame 65,536 bytes including newline.
- Initial backend health is `unknown` and therefore ineligible.
- No automatic replay after a backend failure.

The authoritative contracts are [protocol](docs/protocol.md), [component/API contracts](docs/contracts.md), and [metrics](docs/metrics.md). Contract changes must be reviewed and merged before dependent implementation changes.

## Setup

Python 3.12, Git, and a browser are required. Initial package installation needs internet access; the installed demo must not depend on external services or CDN assets.

### Windows PowerShell

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt -r requirements-dev.txt
python -m pip install --no-deps -e .
python scripts/verify.py
```

If activation is blocked by local policy, call `.\.venv\Scripts\python.exe` directly instead of changing machine-wide policy.

### POSIX shell

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt -r requirements-dev.txt
python -m pip install --no-deps -e .
python scripts/verify.py
```

The dependency set was resolved and import-smoke-tested on Windows with Python 3.12.4 on 6 October 2026. The POSIX commands are documented but not yet verified on this repository.

## Planned runtime topology

```text
traffic generator --TCP :9000--> proxy/service --TCP--> s1 :9101
                                      |          |-----> s2 :9102
browser ----------HTTP :8000----------+          `-----> s3 :9103
```

The dashboard will display application request flow, not captured IP packets. Application failure rate is not packet-loss rate, and active backend work is not CPU utilization.

## Collaboration

All implementation work starts from current `main`, uses one task branch and one worktree, and enters `main` through a reviewed pull request. Member A is the only direct editor of `README.md`; Member B records README input in `docs/readme-notes/Bn.md`. Provider changes merge before consumer changes, and the consumer updates from `main` and reruns its checks before merge.

See [CONTRIBUTING.md](CONTRIBUTING.md) for exact commands and [repository settings](docs/repository-settings.md) for the intended branch-protection rules.
The task order is summarized in [the dependency table](docs/task-dependencies.md).

## Current test commands

```text
python -m pytest tests/unit -q
python -m pytest tests/integration -q
python scripts/verify.py
```

On Windows/Python 3.12, the A4 gate passed 79 automated tests, including 24 integration tests. Its end-to-end path used three real B1 backends, the A service/proxy, automatic health recovery, and the B2 workload client for 30 successful requests at concurrency 6; CSV and API totals reconciled, RR assigned 10/10/10, and cleanup returned all active counts to zero. This is integration evidence, not benchmark evidence.

## Repository map

```text
configs/                 Frozen default runtime configuration
docs/                    Contracts, ownership, test and evidence plans
docs/readme-notes/       Per-task handoff notes; A integrates README
results/                 Generated benchmark evidence (not fabricated)
screenshots/             Repository-relative demonstration evidence
scripts/verify.py        Foundation/configuration verifier
src/netbalance/          Protocol, selectors, registry, metrics, proxy, service
tests/fixtures/          Frozen API fixture
tests/unit/              Mathematical/parsing tests added by tasks
tests/integration/       Real loopback socket/process tests added by tasks
web/                     Offline dashboard assets added by Member B
```

## Next handoff

The next task is B4 benchmark/analyzer dry-run; G4 completes only after B4 merges with nonempty, traceable dry-run artifacts.

Do not claim later gates, test passes, benchmark results, or screenshots until their artifacts exist in the repository.
