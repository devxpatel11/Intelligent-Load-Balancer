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


def test_app_js_uses_safe_dom_methods_no_unsafe_innerhtml() -> None:
    js_path = ROOT / "web" / "app.js"
    js_content = js_path.read_text(encoding="utf-8")

    # The dashboard must avoid innerHTML string interpolation with untrusted API values
    assert ".innerHTML" not in js_content, "app.js should not assign innerHTML"
    assert "textContent" in js_content, "app.js must use textContent for safe text rendering"
    assert "createElement" in js_content, "app.js must use createElement for DOM manipulation"


def test_dashboard_controls_elements_and_handlers() -> None:
    html_path = ROOT / "web" / "index.html"
    html_content = html_path.read_text(encoding="utf-8")

    # Forms and controls present
    assert 'id="form-algorithm"' in html_content
    assert 'id="select-algorithm"' in html_content
    assert 'id="form-weights"' in html_content
    assert 'id="form-reset"' in html_content
    assert 'id="control-notification"' in html_content

    js_path = ROOT / "web" / "app.js"
    js_content = js_path.read_text(encoding="utf-8")

    # API endpoints handled
    assert "/api/algorithm" in js_content
    assert "/api/weights" in js_content
    assert "/api/reset" in js_content
    # Status codes handled
    assert "409" in js_content
    assert "isFetching" in js_content, "Must prevent overlapping fetches"
