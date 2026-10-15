# Team contributions and handoffs

| Role | Name / registration | Owned work | Review duty |
| --- | --- | --- | --- |
| Member A | `devxpatel11` (GitHub) | Protocol, selectors, registry, metrics, proxy, service, configuration, API tests, README/integration | Reviews B PRs |
| Member B | `akshatjha459-byte` (GitHub) | Backend, workload, benchmark, analyzer, demo, web UI, experiment evidence, report drafts | Reviews A PRs |

## Dependency order

```text
C0 -> A1 + B1 -> A2 + B2 -> A3 + B3 -> A4 + B4 -> A5 + B5 -> B6 -> A6 -> G6
```

Provider changes merge first. Consumer branches then update from `main` and rerun their checks. Member B writes task facts/evidence to `docs/readme-notes/Bn.md`; Member A reconciles them into `README.md` only after both daily branches merge.

Contribution claims must link to reviewed commits/PRs, task notes, tests, or evidence paths. C0 foundation work should be attributed to the members who actually reviewed and committed it; do not infer individual credit from this plan.
