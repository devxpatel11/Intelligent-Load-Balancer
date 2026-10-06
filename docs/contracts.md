# Frozen component, configuration, and HTTP contracts

Contract version 1 is the common boundary for A and B. A change to this file, `protocol.md`, `metrics.md`, or `configs/default.json` must be proposed in a dedicated PR, reviewed by both members, and merged before consumer code.

## Runtime topology

| Component | Address | Responsibility |
| --- | --- | --- |
| Workload generator | Outgoing client sockets | Bounded concurrent attempts and raw result records |
| Proxy | TCP `127.0.0.1:9000` | Validate, admit, select/reserve, forward, validate response, account |
| HTTP service/dashboard | HTTP `127.0.0.1:8000` | Immutable snapshots and local controls; no probing in handlers |
| Backend `s1` | TCP `127.0.0.1:9101` | Health/work protocol, default 50 ms base service and capacity 4 |
| Backend `s2` | TCP `127.0.0.1:9102` | Same protocol, independent process |
| Backend `s3` | TCP `127.0.0.1:9103` | Same protocol, independent process |

FastAPI lifespan owns the TCP listener and health loop. Use exactly one Uvicorn worker and no auto-reload during tests or benchmarks because routing state belongs to one event loop.

## Module interfaces

| Owner | Interface | Required result |
| --- | --- | --- |
| A | `protocol.encode_message`, `read_message`, `validate_work` | Shared bounded framing and strict validation; B imports these helpers |
| A | `selectors.select(eligible, state, policy)` | Backend ID or `None`; deterministic `rr`, rotating-tie `lc`, and `swrr` |
| A | `registry.reserve`, `release`, `snapshot` | Atomic select-and-reserve, exactly-once release, immutable snapshots |
| A | Metrics snapshot | Stable schema defined in `metrics.md` and consumed by B |
| B | `python -m netbalance.backend` | `--id`, `--port`, `--service-ms`, `--capacity`; work and health protocol |
| B | `python -m netbalance.workload` | Count/duration, host, port, concurrency, seed, timeout, output, trace, run metadata |
| B | Dashboard assets | Vanilla local HTML/CSS/JS using actual API data; no CDN |

The proxy request path is: read and validate; admit; under one short lock select a healthy backend and reserve active work; release the lock before network I/O; connect/forward/read/validate; release exactly once in `finally`; respond and close.

## Selection contracts

- Eligible means health is exactly `healthy`; `unknown` and `unhealthy` are excluded.
- Backend IDs and ports are unique. Weight is an integer from 1 through 100; booleans are rejected.
- `rr` cycles over stable backend-ID order and skips ineligible entries.
- `lc` selects the smallest reserved active-work count and rotates ties.
- `swrr` adds each eligible configured weight to its current weight, selects the greatest with stable-ID ties, then subtracts the eligible-weight total from the winner.
- Selector state resets when policy, configured weights, or eligible membership changes, and on a successful benchmark reset.
- Active work includes connecting, queued, and processing requests, but excludes health probes.
- Selection and increment are atomic before the first network `await`. Release happens exactly once on success, failure, timeout, disconnect, or cancellation; negative counts are invariant violations, not values to clamp.

## Health contract

- Initial state is `unknown` and ineligible.
- Probe every 1.0 second with a 0.5-second deadline.
- Two consecutive failures move `unknown` or `healthy` to `unhealthy`.
- Two consecutive successes move `unknown` or `unhealthy` to `healthy`.
- Reset the opposite streak after each probe outcome.
- Record the last transition timestamp. Health probes do not affect work totals, assignment counts, latency, or backend capacity.

## Configuration contract

`configs/default.json` is the canonical initial configuration. Required top-level fields are:

- loopback TCP/HTTP hosts and ports;
- `algorithm` in `rr`, `lc`, `swrr`;
- positive `max_inflight`;
- positive client/backend/workload/health deadlines;
- positive failure and recovery thresholds;
- a nonempty backend list with unique ID and port, loopback host, and weight 1-100.

Default values are fixed at max inflight 200, equal weight 1, backend base service 50 ms/capacity 4, and the deadlines/thresholds in the committed configuration.

## HTTP API

All endpoints use JSON. Invalid bodies return FastAPI validation `422` or an explicit `400`; a reset while work is active returns `409`.

| Endpoint | Contract |
| --- | --- |
| `GET /api/metrics` | Immutable schema from `metrics.md`; never performs socket probes |
| `GET /api/config` | Current policy, backend weights, deadlines, thresholds, max inflight, revision |
| `GET /api/health` | Service readiness plus current backend health states |
| `POST /api/algorithm` | Body `{"algorithm":"rr"|"lc"|"swrr"}`; atomic apply, increment config revision, reset selector state |
| `POST /api/weights` | Body `{"weights":{"s1":5,"s2":3,"s3":2}}`; require all configured IDs and weights 1-100; atomic apply/revision/reset |
| `POST /api/reset` | Empty JSON object; allowed only at zero inflight; reset metrics/selector state and increment metrics epoch |

Policy and weight changes affect only later assignments; they do not migrate existing work. Reset does not change configuration or health, and a rejected reset changes no state.

## Overload and cleanup

- `max_inflight` is a global work-admission bound. A well-formed request beyond it receives `OVERLOADED` without a backend reservation.
- Backend connect, complete transaction, and client read operations have finite deadlines.
- Backend response ID and backend identity must match the request and selected configured backend.
- The service owns and cancels its listener, health loop, connection tasks, and sockets on shutdown; no unmanaged background task remains.
