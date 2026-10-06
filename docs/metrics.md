# Frozen metrics contract

Metrics version 1 distinguishes request attempts, assignments, successful responses, and health probes. Snapshots are immutable copies; `GET /api/metrics` does not perform I/O to refresh them.

## Work accounting

For every well-formed `work` frame:

```text
received = inflight + succeeded + failed
rejected <= failed
```

- `received` increments exactly once after protocol validation.
- `inflight` increments on admission and decrements exactly once at the terminal outcome.
- `succeeded` counts valid successful downstream responses returned to the client.
- `failed` counts every terminal unsuccessful well-formed work request, including admission errors, backend errors, timeouts, protocol errors, disconnects, and cancellation.
- `rejected` is the subset of failures refused before backend assignment, such as overload or no eligible backend.
- `protocol_errors` counts malformed/non-work frames and is outside the work-accounting equation.

For each backend:

```text
assignments = active + successes + failures
active >= 0
```

An assignment occurs with the atomic backend reservation. Health probes never affect these counters.

## Latency and throughput

- Client latency: `perf_counter()` from before client connect through receipt and validation of a response. Save successful and failed durations separately.
- Proxy latency: from validated work acceptance to downstream terminal outcome; label it separately from client latency.
- Live latency fields use successful proxy outcomes only and report milliseconds.
- Mean, p50, and p95 derive from the same saved successful-latency series.
- Nearest-rank percentile: `sorted[ceil(q * N) - 1]`; if `N == 0`, return `null`.
- Successful throughput: successful client requests divided by measured run duration in seconds. The duration starts before the first measured attempt and ends after all measured attempts terminate; warm-up/setup are excluded.
- Application failure rate: `100 * unsuccessful client attempts / all client attempts`.

Do not call application failure rate packet loss. Do not call active reservations CPU, memory, or bandwidth utilization.

## Snapshot schema

`tests/fixtures/metrics.json` is the canonical empty/sample-shaped response. Required top-level fields:

- `schema_version`: integer `1`;
- `metrics_epoch`: increments once on each successful reset;
- `config_revision`: increments once on each successful policy or weight update;
- `algorithm`: current policy;
- `inflight`: current global accepted work;
- `totals`: `received`, `succeeded`, `failed`, `rejected`, `protocol_errors`;
- `successful_proxy_latency_ms`: `count`, `mean`, `p50`, `p95`;
- `backends`: stable ID-ordered records;
- `events`: at most the 200 most recent event records.

Each backend record contains `id`, host/port, configured weight, health state, active, assignments, successes, failures, consecutive probe streaks, and last transition timestamp.

Each recent event contains timestamp, request ID or `null`, action (`assign`, `success`, `error`, `health_transition`, `config_change`, `reset`), backend ID or `null`, outcome, error code or `null`, and latency milliseconds or `null`. Payload contents are never retained.

## Reset

A successful idle reset:

- increments `metrics_epoch`;
- zeroes work/backend counters and successful latency samples;
- clears recent events before recording the reset event if the implementation chooses to expose it;
- resets selector state;
- preserves backend configuration, `config_revision`, and current health.

A busy or invalid reset changes nothing.
