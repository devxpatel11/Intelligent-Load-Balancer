# Controlled experiment plan

This document defines planned evidence; it contains no measured results.

| Scenario | Backend/workload profile | Question |
| --- | --- | --- |
| S1 uniform | All 50 ms, capacity 4, weights 1:1:1; concurrency 1 and 30 | Are distributions fair under equal servers? |
| S2 slow server | s1/s3 50 ms, s2 200 ms; capacity 4; weights 1:1:1; concurrency 30 | Does LC reduce pressure on slow s2? |
| S3 unequal capacity | All 50 ms; capacities 5:3:2; weights 5:3:2; concurrency 30 | Does SWRR follow configured capacity preference? |
| S4 failure/recovery | Uniform; stop s2 after 3 s, restart after 8 s, about 15 s total | How do detection, exclusion, and recovery affect failures? |

For S1-S3, plan four workload profiles by three policies by three repetitions: 36 measured runs. Each run uses 30 warm-up requests, then 300 measured requests. Rotate policy order and reuse each profile/repetition seed and trace across policies.

Before measurement: start the exact backend profile, wait for healthy state, apply policy/weights, warm up, wait for zero inflight, reset, and save the returned epoch. Measure from before the first measured attempt until every measured attempt terminates.

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

Required raw columns are `request_id`, `policy`, `scenario`, `repetition`, `started_offset_s`, `latency_ms`, `ok`, `backend_id`, and `error_code`. Reports show successful throughput, successful p95 latency, assignments by backend, and failures separately. A single outage demo is not a statistically strong comparison.
