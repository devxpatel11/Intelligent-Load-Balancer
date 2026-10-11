# Test and acceptance plan

Use unit tests for selector mathematics and parsing. Use real loopback sockets/processes for integration behavior, ephemeral ports, bounded readiness polling, and owned-process cleanup. Timing performance is evidence, not a unit-test pass condition.

| ID | Owner | Required check | Required outcome |
| --- | --- | --- | --- |
| T01 | A | RR, 30 sequential assignments, all healthy | 10/10/10; skip unhealthy nodes |
| T02 | A | LC counts 5/1/3, ties, concurrent reserve | Select s2; rotate ties; no simultaneous stale choice |
| T03 | A | SWRR 100 at 5:3:2; membership change | 50/30/20 stable; never choose unhealthy |
| T04 | A+B | Split frame, malformed JSON, EOF, oversized frame | One valid response or bounded error/close; no hang |
| T05 | B | Backend capacity and nonblocking health | Bound work concurrency; health remains responsive |
| T06 | A+B | 30 requests through proxy and three backends at concurrency 6 | IDs, echo, backend identity match; raw results saved |
| T07 | A | Kill and restart backend | Exclude after threshold; later rejoin; bounded detection-window failures |
| T08 | A | All down; downstream hangs | Structured errors in deadline; active returns to zero |
| T09 | A | Disconnect/cancel/shutdown during work | No negative/leaked counts, tasks, or sockets |
| T10 | A+B | Policy/weights/reset API validation | 400/422 invalid; 409 busy reset; valid reset increments epoch |
| T11 | B | Workload bounds, timeout, empty success set | Bounded tasks; categorized failure; null percentiles |
| T12 | B | Analyzer known latencies and CSV reconciliation | Exact mean/nearest-rank percentile/throughput |
| T13 | B | UI live, empty, down, error, offline assets | No fake metrics; real controls; bounded events |
| T14 | A+B | Fresh checkout install and demo shutdown | Commands work; owned children cleaned; ports reusable |
| T15 | A+B | Benchmark metadata and report claims | Every number traces to saved config/data/version |

Planned commands after their corresponding files exist:

```text
python -m pytest tests/unit -q
python -m pytest tests/integration -q
python scripts/verify.py
```

At A2, 24 unit tests and 8 real-socket/service integration tests pass on Windows with Python 3.12.4. The 30-request test uses three contract-faithful loopback stubs, so it proves the A2 proxy path but does not claim B1 or the combined G2 gate.
