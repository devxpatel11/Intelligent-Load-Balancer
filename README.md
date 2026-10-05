**ThermoSched - CPU Thermal Manager (Thermal-Pacing Scheduler)**
ThermoSched is a Linux user-space prototype that makes CPU placement decisions using thermal state, CPU utilization, process heat intensity, and temperature trend. It proactively migrates managed workloads to safer cores and can insert short, bounded micro-breaks when no safe destination exists.
> Project scope: an Operating Systems academic prototype. It does not replace the Linux kernel scheduler and it must only control workloads explicitly launched or allowlisted by the user.
Why this project exists
Conventional scheduling focuses primarily on fairness, utilization, capacity, and latency. Under sustained CPU load, hardware thermal controls can reduce frequency to protect the processor. ThermoSched demonstrates a feedback loop that reacts earlier: observe thermal/CPU state, estimate risk, move a hot workload, and pace it briefly only if migration cannot help.
Core features
- Linux thermal discovery through `/sys/class/thermal` and `/sys/class/hwmon` when available.
- Deterministic simulation mode when the host does not expose useful per-core thermal sensors.
- Per-core CPU utilization and managed-process CPU profiling.
- Thermal risk score using temperature or modeled thermal state, utilization, and temperature trend.
- Proactive CPU-affinity migration for managed PIDs.
- Bounded micro-break pacing using `SIGSTOP` / `SIGCONT` when every candidate core is unsafe.
- Anti-thrashing controls: hysteresis, minimum residency, migration cooldown, and minimum-improvement checks.
- CSV/JSONL event logs and run summaries.
- Baseline-vs-thermal-aware benchmark mode.
- Terminal status view and reproducible demo scripts.

**Architecture**
Managed Workload
      |
      v
Process Profiler -----> Core State Estimator <----- Thermal/Sensor Layer
                              |
                              v
                      Thermal Policy Engine
                              |
                    +---------+----------+
                    |                    |
                    v                    v
             CPU Affinity Move      Micro-break
                    |                    |
                    +---------+----------+
                              |
                              v
                       Event Logger/UI

**Safety boundary**
ThermoSched must not pause or repin arbitrary system processes. The default mode should manage only child processes launched by ThermoSched. An explicit `--pid` mode may be supported only for PIDs owned by the current user and must reject protected/system PIDs. On shutdown or failure, the controller must resume any paused managed process and restore its original affinity.
Requirements
- Linux
- Python 3.10+
- `psutil`
- `PyYAML`
- `rich` (terminal UI)
- `matplotlib` (result plots; optional at runtime)
- Optional: `stress-ng` for external stress experiments

**Quick start**
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m thermosched doctor
python -m thermosched launch --mode simulate -- python workloads/cpu_burn.py --seconds 90
For a real-sensor run, use:
python -m thermosched launch --mode auto -- python workloads/cpu_burn.py --seconds 90
To manage an existing user-owned test PID:
python -m thermosched monitor --pid <PID> --mode auto --duration 90

**Demo workflow**
1. Run `python -m thermosched doctor` and record available CPUs and sensors.
2. Run a baseline workload without thermal-aware control.
3. Run the same workload with ThermoSched.
4. Observe migration/pacing events in the terminal.
5. Compare peak temperature/thermal score, time above the high threshold, throughput, migration count, and pacing time.
6. Generate the summary plot/report from the run logs.
   
**Configuration**
Example `config/default.yaml`:
sampling_interval_s: 0.5
high_temp_c: 75.0
critical_temp_c: 82.0
hysteresis_c: 3.0
min_residency_s: 2.0
migration_cooldown_s: 1.5
min_destination_improvement: 0.15
microbreak_ms: 150
max_microbreak_ms: 250
risk_weights:
  thermal: 0.55
  utilization: 0.30
  trend: 0.15
simulation:
  ambient_c: 42.0
  heat_gain_per_s: 2.0
  cooling_per_s: 1.25
  throttle_temp_c: 85.0
  
Thresholds are deliberately configurable because safe/meaningful temperatures differ by hardware. Do not hard-code a claim that one temperature is universally safe.

**Repository layout**
thermosched/
  __init__.py
  __main__.py
  cli.py
  config.py
  models.py
  sensors/
    base.py
    linux_thermal.py
    hwmon.py
    simulated.py
  telemetry/
    cpu.py
    process.py
  scheduler/
    heat.py
    policy.py
    actuator.py
    controller.py
  logging/
    event_logger.py
  dashboard/
    terminal.py
workloads/
  cpu_burn.py
  bursty.py
scripts/
  run_demo.sh
  compare_runs.py
config/
  default.yaml
tests/
  test_policy.py
  test_actuator.py
  test_sensors.py
  test_controller.py
  test_safety.py
docs/
  experiment_results.md

  
**Scheduling policy**
At each sampling interval, ThermoSched builds a state for every candidate CPU. The controller evaluates the currently assigned CPU for each managed workload. A migration is considered if the current CPU crosses the configured thermal/risk trigger for consecutive samples. A destination must be cooler/safer by a minimum margin and must not violate cooldown or minimum-residency rules. If all candidate CPUs are unsafe, the process receives a short bounded pause before the next evaluation.
The policy intentionally includes hysteresis and cooldown to avoid rapid back-and-forth migrations.
Logs and metrics
Each decision should record at least:
- timestamp
- PID
- current CPU
- destination CPU, if any
- action: `stay`, `migrate`, `pace`, `resume`, `restore`
- temperature or thermal score per candidate CPU
- per-core utilization
- process CPU utilization
- reason code
- pacing duration
The final summary should report:
- total runtime
- throughput or workload progress
- peak measured package temperature (if available)
- peak simulated/core thermal state (simulation mode)
- time above configured high threshold
- migration count
- pacing count and total pacing time
- controller overhead


**Testing**
pytest -q
python -m thermosched doctor
python -m thermosched launch --mode simulate -- python workloads/cpu_burn.py --seconds 30
python scripts/compare_runs.py --baseline logs/baseline.csv --aware logs/aware.csv

**Critical automated tests should cover:**
- no migration below trigger
- migration from a hot core to a meaningfully safer core
- no migration during cooldown/minimum-residency window
- hysteresis prevents oscillation
- all-hot case invokes bounded pacing
- missing sensors cleanly activate simulation/fallback behavior
- process exit mid-run does not crash the controller
- permission errors are reported clearly
- shutdown restores affinity and resumes any paused managed process

  
**Baseline comparison**
A valid academic result does not require claiming that every laptop will show a large physical temperature drop. The report must distinguish measured package temperature from modeled per-core thermal state. The important evidence is that the controller observes state, makes deterministic policy decisions, performs affinity changes, avoids thrashing, and records the trade-off between thermal risk and throughput.
Known limitations
- Many consumer systems expose package or thermal-zone temperature rather than a sensor for each logical CPU.
- CPU affinity is not the same as rewriting the kernel scheduler; the Linux scheduler still operates inside the allowed affinity mask.
- Multi-threaded applications can require per-thread affinity handling. The reference demo should use separate worker processes for predictable control.
- Fan curves, firmware, CPU boost behavior, and hardware throttling differ across machines.
- Real thermal response has inertia, so short experiments may show modest physical differences.
  
**Future work**
- Per-thread affinity management for multi-threaded applications.
- cgroup v2 integration and utilization-clamp experiments.
- eBPF trace collection for migration/latency visibility.
- Kernel-level prototype using scheduler thermal-pressure signals.
- Web dashboard and multi-host experiment runner.
  
Team ownership
- Member A: scheduler policy, actuator, controller, integration/release.
- Member B: sensors, telemetry, simulation model, metrics/experiments.
- Member C: workloads, CLI/UI, automated tests, README/demo documentation.
License
Academic/educational prototype.
