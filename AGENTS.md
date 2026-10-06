# Repository working agreement

These rules apply to every file in this repository. Read this file, `docs/contracts.md`, `docs/protocol.md`, and the current task's dependencies before editing code.

## Non-negotiable design

- Target Python 3.12 using `asyncio` TCP streams.
- Use one UTF-8 newline-delimited JSON request and response per TCP connection.
- Preserve the frozen contracts in `docs/protocol.md`, `docs/contracts.md`, and `docs/metrics.md`.
- Run FastAPI/Uvicorn with exactly one worker and no auto-reload during tests or benchmarks.
- Use real loopback sockets for integration evidence. Fixtures are not integration evidence.
- Do not add cloud services, Docker, a database, Node, ML, UDP, TLS, or a CDN for the core build.
- Do not fabricate results, test outcomes, screenshots, package compatibility, or implemented features.

## Ownership

Member A owns:

- `src/netbalance/protocol.py`, `selectors.py`, `registry.py`, `metrics.py`, `proxy.py`, `service.py`
- configuration and API tests
- `README.md`, `AGENTS.md`, and daily integration

Member B owns:

- `src/netbalance/backend.py`, `workload.py`, `benchmark.py`, `analyze.py`, `demo.py`
- `web/`, generated evidence, report drafts, UI/generator tests

Shared contract files are freeze points, not casually shared edit areas. A proposed contract change must be a small dedicated PR, approved by both members, and merged before dependent code. Member A edits `README.md`; Member B supplies facts and evidence in `docs/readme-notes/Bn.md`.

## Task and gate sequence

| Day | Member A | Member B | Gate after both merge |
| --- | --- | --- | --- |
| 1 | A1 protocol/selectors/registry | B1 backend | G1 contracts, selectors, direct backend |
| 2 | A2 proxy/service/API | B2 workload/minimal dashboard | G2 30 real RR requests and live API |
| 3 | A3 health/deadlines/cleanup/controls | B3 live controls/launcher/fault evidence | G3 outage, recovery, all-down, timeout, cleanup |
| 4 | A4 integration/fault/accounting tests | B4 benchmark/analyzer dry run | G4 essential tests and nonempty dry-run artifacts |
| 5 | A5 clean-checkout verification/README | B5 repeated experiments/report/evidence | G5 reproducible checkout and traceable results |
| 6 | A6 release/README/final checks | B6 evidence audit/rehearsal | G6 consistent code, docs, evidence, demo |

Hard prerequisites must be merged and their gate passed before integration. A soft dependency may use an explicitly labelled fixture, but a fixture never satisfies a live gate.

## Branch and worktree rules

- Never implement on `main`; only reviewed integration commits land there.
- Use one branch and one worktree per task: `feature/A1-short-name`, `feature/B1-short-name`, and so on.
- Do not run two coding agents in the same worktree.
- Start from current `main`; update the branch from `origin/main` immediately before review and rerun its checks.
- Commit only task-owned files. Do not overwrite a teammate's uncommitted work, force-push `main`, or use `git reset --hard` for routine conflict resolution.
- A reviews B; B reviews A. Merge provider work first, then update and retest the consumer branch.
- Prefer squash-merging task PRs. Never force-push a branch after review has begun; add a merge commit from `origin/main` instead.
- Only one PR is merged into `main` at a time. The next PR must update from the new `main` and pass again.

Exact commands and conflict handling are in `CONTRIBUTING.md`.

## Implementation rules

- Keep the design small and direct; no speculative abstraction or optional infrastructure.
- Validate all external input and bound frames, concurrency, event history, deadlines, and process cleanup.
- Selection and backend active-count reservation occur atomically before any network `await`; release exactly once in `finally` on every outcome.
- Never hold a registry lock across connect, read, or write operations.
- Health probes bypass backend work slots and never count as work traffic.
- Initial `unknown` and `unhealthy` backends are ineligible.
- Tests use ephemeral ports, readiness polling, finite deadlines, and owned subprocess cleanup instead of arbitrary sleeps or unrelated-process termination.
- Generated results must include raw inputs/configuration, environment, commit identity, and summary output. Sample or synthetic fixtures must be labelled as such.

## Required handoff

Every task ends with this information in `docs/readme-notes/<TASK>.md` and the PR description:

```text
Task ID / branch / commit:
Implemented behavior:
Changed files and contract changes:
Exact commands run and actual results:
Expected versus actual acceptance criteria:
Raw evidence paths:
Known limitations / blocked items:
Next task ready? yes/no, with reason:
README notes path:
```

A task is not merge-ready until its relevant tests pass, the diff contains only owned work, documentation states actual rather than planned behavior, and the reviewer can reproduce the reported command results.
