# Demonstration and rehearsal

Run the bounded release rehearsal first:

```text
python scripts/rehearse_demo.py
```

It starts the real three-backend topology and single-worker service, waits for health, loads the dashboard, sends 30 RR requests, requires 30/30 success with `10:10:10` assignments, stops only its child processes, and verifies that ports 8000, 9000, and 9101-9103 are reusable. B6 recorded a successful rehearsal.

For the interactive presentation, run:

```text
python -m netbalance.demo --profile uniform
```

Then open `http://127.0.0.1:8000/` and present in this order:

1. Show all three independently configured backends as healthy.
2. Run 30 RR requests and show the equal assignment distribution.
3. Switch to LC and explain that active reservations, not CPU or network utilization, drive selection.
4. Apply weights `5:3:2`, switch to SWRR, and show the configured weighted distribution.
5. Explain the committed outage/recovery evidence: detection, exclusion, bounded failures, recovery, and no replay.
6. Open `results/experiments/comparison.png`, then trace one aggregate result back to its raw CSV, configuration, environment, trace, summary, and proxy metrics.
7. Stop the launcher with `Ctrl+C` and state that it terminates only its owned children.

Use “request flow,” not packet capture, and “application failures,” not packet loss. If the dashboard cannot be displayed, use `/api/health`, `/api/config`, `/api/metrics`, CLI output, and the committed chart as the fallback.
