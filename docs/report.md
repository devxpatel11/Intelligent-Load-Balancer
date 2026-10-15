# NetBalance implementation and experiment report

## Problem and objectives

NetBalance demonstrates how routing policy, backend speed, capacity, health state, and bounded concurrency affect an application-aware TCP service. The objective is a reproducible local system—not a production edge proxy—that compares Round Robin (RR), Least Connections (LC), and Smooth Weighted Round Robin (SWRR) using real loopback sockets and traceable measurements.

The implementation targets Python 3.12. It intentionally excludes cloud services, containers, databases, Node, ML, UDP, TLS, and CDNs.

## Architecture

The single FastAPI/Uvicorn process owns the HTTP API, health loop, registry, metrics, and TCP proxy. Uvicorn runs with one worker because routing and metric state live in one event loop. Three independent backend processes listen on ports 9101-9103; the proxy listens on TCP 9000; the API and offline dashboard use HTTP 8000.

```text
workload -- TCP :9000 --> proxy/registry/metrics -- TCP --> backend processes
browser  -- HTTP :8000 -----------+
```

The exact boundaries are frozen in [protocol.md](protocol.md), [contracts.md](contracts.md), and [metrics.md](metrics.md).

## Protocol and routing

Each connection carries exactly one UTF-8 JSON request line and one response line. The 65,536-byte frame bound, strict work validation, stable error codes, and finite client/connect/backend deadlines prevent unbounded reads and hangs. A failed assigned request is not replayed because work may be non-idempotent.

Policy behavior, simplified:

```text
RR:   choose the next healthy backend in stable ID order
LC:   choose the healthy backend with the smallest reserved active count;
      rotate ties
SWRR: add each healthy backend's weight to its current weight;
      choose the greatest; subtract the eligible total from the winner
```

Selection and active-count reservation happen atomically before network I/O. The registry lock is released before connect/read/write awaits, and one `finally` path releases each reservation exactly once.

## Health, controls, and metrics

Backends begin `unknown` and ineligible. The service probes every second with a 0.5-second deadline; two failures mark a backend unhealthy and two successes restore it. Probes bypass work slots and do not enter work metrics.

The API exposes immutable health/config/metrics snapshots plus validated policy, weight, and idle-reset controls. Accounting enforces:

```text
received = inflight + succeeded + failed
assignments = active + successes + failures
```

Successful throughput is successful client responses divided by the complete measured duration. Latencies are client-observed successful durations. Percentiles use nearest rank: `sorted[ceil(q * N) - 1]`. Failures are reported separately and are never called packet loss.

## Setup and operation

Create a Python 3.12 virtual environment, install `requirements-dev.txt`, install the package editable with `--no-deps`, and run `python scripts/verify.py`. Start the live topology with:

```text
python -m netbalance.demo --profile uniform
```

The dashboard is available at `http://127.0.0.1:8000/`. The complete verified commands are in the repository [README](../README.md).

## Controlled experiment method

The B5 matrix followed [experiments.md](experiments.md): four profiles × three policies × three repetitions = 36 measured runs. Every run used 30 warm-up requests followed by 300 measured requests. Policy order rotated per repetition, and all policies within a profile/repetition used byte-identical seeded traces.

Before each measurement the runner applied the policy and complete weight set, completed warm-up, reset idle metrics, saved the returned epoch, then reconciled client rows against the proxy snapshot. Each run retains `raw.csv`, `summary.json`, `config.json`, `environment.json`, `trace.json`, and `proxy-metrics.json` under `results/experiments/<scenario>/<policy>/<repetition>/`.

The evidence was generated on Windows 11 with Python 3.12.4 from commit `5302023a3c6b65b71c9949a09fb418dd1560623e`. The 36 measured runs completed in 519.25 seconds. Aggregate values below are medians of three repetitions; success/failure counts are totals across 900 attempts.

## Measured results

| Profile | Policy | Success | Failure | Median throughput (req/s) | Median successful p95 (ms) |
| --- | --- | ---: | ---: | ---: | ---: |
| Uniform, concurrency 1 | RR | 900 | 0 | 8.72 | 171.70 |
| Uniform, concurrency 1 | LC | 900 | 0 | 8.77 | 171.64 |
| Uniform, concurrency 1 | SWRR | 900 | 0 | 8.72 | 171.85 |
| Uniform, concurrency 30 | RR | 900 | 0 | 104.35 | 392.65 |
| Uniform, concurrency 30 | LC | 900 | 0 | 106.65 | 361.22 |
| Uniform, concurrency 30 | SWRR | 900 | 0 | 103.77 | 379.50 |
| Slow s2, concurrency 30 | RR | 862 | 38 | 28.27 | 2837.29 |
| Slow s2, concurrency 30 | LC | 900 | 0 | 70.32 | 1018.42 |
| Slow s2, concurrency 30 | SWRR | 867 | 33 | 28.19 | 2848.94 |
| Capacity 5:3:2, concurrency 30 | RR | 900 | 0 | 56.31 | 1309.91 |
| Capacity 5:3:2, concurrency 30 | LC | 900 | 0 | 87.26 | 590.00 |
| Capacity 5:3:2, concurrency 30 | SWRR | 900 | 0 | 86.51 | 495.29 |

Source: [aggregate.csv](../results/experiments/aggregate.csv), derived from the committed per-run raw files. The comparison chart is [comparison.png](../results/experiments/comparison.png).

### Interpretation

- With one concurrent request and equal servers, all policies behaved equivalently: every policy assigned 300 requests to each backend across repetitions, and median throughput/p95 differed by less than 1%.
- With 30 concurrent requests and equal servers, all policies completed 900/900. LC had modestly higher median throughput and lower p95, but the small three-repetition sample does not establish a general performance ranking.
- With slow `s2`, LC shifted assignments to `405/120/375`, completed 900/900, and reached 70.32 requests/s. RR and SWRR continued equal distribution pressure, producing 38 and 33 `BACKEND_TIMEOUT` failures respectively and about 28 requests/s. These are bounded application failures, not packet loss.
- With capacities/weights 5:3:2, SWRR assigned exactly `450/270/180` across 900 requests (50%/30%/20%). It achieved 86.51 requests/s and the lowest median p95 of 495.29 ms. LC adapted to active counts (`431/265/204`) and had similar throughput; RR's equal `300/300/300` distribution underused the larger backend and overloaded the smaller one relative to its capacity.

## Fault and acceptance evidence

The 90-test post-experiment suite covers strict framing, selectors, atomic reservations, backend capacity, nonblocking health, real 30-request routing, outage/recovery, all-down, backend timeout, disconnect/cancellation cleanup, API validation, workload bounds, exact analyzer math, dashboard behavior, benchmark metadata, and owned-process cleanup.

The separate B3 live outage run stopped `s2` near 3 seconds and restarted it near 8 seconds. It recorded 679 successful and 22 bounded `BACKEND_UNAVAILABLE` responses across 701 attempts, then observed `s2` healthy with all active counts at zero. This single run demonstrates behavior but is not used as a statistically strong policy comparison.

## Limitations

- Results describe one Windows host, loopback networking, simulated service times, three repetitions, and this exact commit; they are not internet-scale or production capacity claims.
- The experiment does not measure OS CPU, memory, bandwidth, packets, TLS, multi-host latency, or multi-worker coordination.
- Python scheduling and host load affect timings. Raw rows and environment/config snapshots are retained so differences can be audited.
- The default health thresholds allow a finite detection window; assigned work can fail during transitions, and requests are deliberately not replayed.
- Linux behavior is covered by the repository CI definition but the reconstructed branch must run remotely before claiming a successful hosted CI execution.

## Conclusion and future work

The evidence shows that equal servers make policy differences small, LC is effective when service speed differs, and SWRR precisely follows declared capacity weights. The design remains deliberately small and auditable.

Future work, outside the core build, could increase repetitions on multiple hosts, add confidence intervals, and compare mixed traces. Production features such as TLS, persistent connections, distributed state, and autoscaling require a different scope and threat model.

## Traceable contributions and references

Member A owns protocol, selectors, registry, metrics, proxy, service, API/configuration tests, README integration, and daily gates. Member B owns backend, workload, dashboard, launcher, benchmark, analyzer, experiment tooling/evidence, and this report draft. Exact task commits and commands are recorded in `docs/readme-notes/A1.md` through `B5.md`; attribution is based on reviewed history, not inferred identity.

References:

- Python 3.12 `asyncio` streams and synchronization documentation.
- FastAPI lifespan and static-file documentation.
- RFC 8259, The JavaScript Object Notation (JSON) Data Interchange Format.
- Repository frozen contracts and committed raw experiment evidence cited above.
