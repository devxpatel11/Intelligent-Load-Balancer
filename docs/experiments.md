# Controlled experiment plan and execution record

The S1-S3 matrix below was executed for B5 at commit `5302023a3c6b65b71c9949a09fb418dd1560623e`. The S4 outage/recovery demonstration was executed separately for B3 and remains a single behavioral run, not a comparative experiment.

| Scenario | Backend/workload profile | Question |
| --- | --- | --- |
| S1 uniform | All 50 ms, capacity 4, weights 1:1:1; concurrency 1 and 30 | Are distributions fair under equal servers? |
| S2 slow server | s1/s3 50 ms, s2 200 ms; capacity 4; weights 1:1:1; concurrency 30 | Does LC reduce pressure on slow s2? |
| S3 unequal capacity | All 50 ms; capacities 5:3:2; weights 5:3:2; concurrency 30 | Does SWRR follow configured capacity preference? |
| S4 failure/recovery | Uniform; stop s2 after 3 s, restart after 8 s, about 15 s total | How do detection, exclusion, and recovery affect failures? |

For S1-S3, the run used four workload profiles by three policies by three repetitions: 36 measured runs. Each run used 30 warm-up requests, then 300 measured requests. Policy order rotated, and each profile/repetition seed and trace was reused across policies.

Before measurement, the runner started the exact backend profile, waited for healthy state, applied policy/weights, warmed up, waited for workload completion, reset at zero inflight, and saved the returned epoch. Measurement began before the first measured attempt and ended after all measured attempts terminated.

Save one row per attempt and retain:

```text
results/<scenario>/<policy>/<repetition>/
  raw.csv
  summary.json
  config.json
  environment.json
  trace.json
  proxy-metrics.json
```

Required raw columns are `request_id`, `policy`, `scenario`, `repetition`, `started_offset_s`, `latency_ms`, `ok`, `backend_id`, and `error_code`. Reports show successful throughput, successful p95 latency, assignments by backend, and failures separately. A single outage demo is not a statistically strong comparison. The executed matrix, aggregate table, chart, commit identity, elapsed time, and all per-run files are under `results/experiments/`; interpreted results are in `docs/report.md`.

Audit the committed matrix without regenerating or overwriting it:

```text
python scripts/audit_evidence.py
```

B6 reconciled all 36 runs, 10,800 measured attempts, and 217 indexed files.
