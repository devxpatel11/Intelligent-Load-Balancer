import json
from pathlib import Path

import pytest

from netbalance.config import load_config

ROOT = Path(__file__).resolve().parents[2]


def test_default_config_loads() -> None:
    config = load_config(ROOT / "configs/default.json")
    assert (config.listen_host, config.listen_port) == ("127.0.0.1", 9000)
    assert [backend.id for backend in config.backends] == ["s1", "s2", "s3"]


@pytest.mark.parametrize(
    "change",
    [
        {"algorithm": "random"},
        {"max_inflight": True},
        {"backends": [
            {"id": "s1", "host": "127.0.0.1", "port": 9101, "weight": 1},
            {"id": "s1", "host": "127.0.0.1", "port": 9102, "weight": 1},
        ]},
        {"backends": [{"id": "s1", "host": "127.0.0.1", "port": 9101, "weight": True}]},
    ],
)
def test_invalid_config_is_rejected(tmp_path: Path, change: dict[str, object]) -> None:
    raw = json.loads((ROOT / "configs/default.json").read_text(encoding="utf-8"))
    raw.update(change)
    path = tmp_path / "config.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(path)
