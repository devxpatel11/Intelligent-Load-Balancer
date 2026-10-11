"""Tests for dashboard assets and metrics fixture schema mapping."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_dashboard_files_exist_and_no_cdn() -> None:
    html_path = ROOT / "web" / "index.html"
    css_path = ROOT / "web" / "style.css"
    js_path = ROOT / "web" / "app.js"

    assert html_path.is_file(), "index.html must exist"
    assert css_path.is_file(), "style.css must exist"
    assert js_path.is_file(), "app.js must exist"

    html_content = html_path.read_text(encoding="utf-8")
    assert "http://" not in html_content and "https://" not in html_content, "No external CDN links in index.html"
    assert "cdn" not in html_content.lower(), "No CDN references in index.html"

    css_content = css_path.read_text(encoding="utf-8")
    assert "http://" not in css_content and "https://" not in css_content, "No external CDN links in style.css"


def test_metrics_fixture_matches_dashboard_schema() -> None:
    fixture_path = ROOT / "tests" / "fixtures" / "metrics.json"
    with open(fixture_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Validate elements rendered by app.js exist in fixture
    assert "algorithm" in data
    assert "inflight" in data
    assert "metrics_epoch" in data
    assert "config_revision" in data
    assert "totals" in data
    for k in ("received", "succeeded", "failed", "rejected", "protocol_errors"):
        assert k in data["totals"]

    assert "successful_proxy_latency_ms" in data
    for k in ("count", "mean", "p50", "p95"):
        assert k in data["successful_proxy_latency_ms"]

    assert "backends" in data
    assert len(data["backends"]) == 3
    for b in data["backends"]:
        for k in ("id", "host", "port", "weight", "health", "active", "assignments", "successes", "failures"):
            assert k in b

    assert "events" in data
    assert isinstance(data["events"], list)
