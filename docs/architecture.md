# Architecture

## Processes and data flow

```text
bounded workload clients
        |
        | TCP :9000, one JSON line per connection
        v
FastAPI/Uvicorn service (one worker / one event loop)
  - TCP proxy listener
  - selector + backend registry
  - health probe loop
  - metrics/event state
  - HTTP API + static dashboard on :8000
        |
        +---- TCP :9101 ---- backend s1 process
        +---- TCP :9102 ---- backend s2 process
        `---- TCP :9103 ---- backend s3 process
```

The proxy is application-aware: it parses one framed request, selects one configured service backend, and forwards that request. It is not an IP router, transparent packet forwarder, kernel scheduler, production reverse proxy, or packet-capture system.

## Concurrency boundary

Shared routing and accounting state lives in one event loop. A short registry lock covers eligibility inspection, selection, and active reservation. Network connection/read/write operations happen after the lock is released. Every reservation has one owner and one `finally` release path.

Backends are independent processes. Each backend uses a work semaphore for configured capacity, while the health operation bypasses work slots. The workload generator bounds concurrent client tasks rather than creating all requests at once.

## State ownership

- Configuration: immutable validated base plus atomic policy/weight updates.
- Registry: backend health, streaks, selector state, and active reservations.
- Metrics: counters, successful proxy latency samples/summary, and a bounded 200-event deque.
- HTTP handlers: return copied state; they do not probe sockets or mutate routing state except through documented control endpoints.

Detailed behavior is authoritative in `protocol.md`, `contracts.md`, and `metrics.md`.
