import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

from netbalance.benchmark import main
from netbalance.workload import AttemptResult, WorkloadSummary


def test_benchmark_writes_traceable_metadata(tmp_path: Path) -> None:
    result = AttemptResult("r1", "rr", "test", 1, 0.0, 10.0, True, "s1", None)
    summary = WorkloadSummary(1, 1, 0, 0.5, 2.0, 10.0, 10.0, 10.0, 10.0)
    output = tmp_path / "run.csv"
    with (
        patch("netbalance.benchmark.run_workload", new_callable=AsyncMock, return_value=([result], summary)),
        patch("netbalance.benchmark.get_git_commit", return_value="abc123"),
        patch("netbalance.benchmark.get_config_from_service", return_value={"algorithm": "rr"}),
    ):
        assert main(["--count", "1", "--output", str(output)]) == 0

    metadata = json.loads((tmp_path / "run.csv.meta.json").read_text(encoding="utf-8"))
    assert metadata["git_commit"] == "abc123"
    assert metadata["service_config"] == {"algorithm": "rr"}
    assert metadata["summary"]["duration_s"] == 0.5
    assert metadata["environment"]["python"]
    assert output.read_text(encoding="utf-8").count("\n") == 2


def test_benchmark_does_not_write_untraceable_results(tmp_path: Path) -> None:
    output = tmp_path / "run.csv"
    with patch("netbalance.benchmark.get_config_from_service", side_effect=OSError("offline")):
        assert main(["--count", "1", "--output", str(output)]) == 1
    assert not output.exists()
