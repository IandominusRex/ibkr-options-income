"""Tests for scripts/start.py's service registration and CLI flag wiring.

Covers the two services the launcher supervises alongside the original
approval/monitor/EOD trio: the web API and the research worker (neither holds an
ib_async connection or clientId, so they're safe to add to the same supervised
subprocess pool — see CLAUDE.md's one-clientId-per-process invariant).
"""

from __future__ import annotations

import scripts.start as start


def test_api_service_registered():
    assert start.SERVICES["api"]["module"] == "scripts.run_api"


def test_research_service_registered():
    assert start.SERVICES["research"]["module"] == "scripts.run_research_worker"


def test_all_services_active_by_default():
    parser = start._build_parser()
    args = parser.parse_args([])
    assert set(start._active_services(args)) == set(start.SERVICES)


def test_no_api_flag_excludes_only_api():
    parser = start._build_parser()
    args = parser.parse_args(["--no-api"])
    active = start._active_services(args)
    assert "api" not in active
    assert "research" in active
    assert "monitor" in active
    assert "approval" in active


def test_no_research_flag_excludes_only_research():
    parser = start._build_parser()
    args = parser.parse_args(["--no-research"])
    active = start._active_services(args)
    assert "research" not in active
    assert "api" in active


def test_spreads_service_is_supervised_and_can_be_skipped():
    assert start.SERVICES["spreads"]["module"] == "scripts.run_spreads"
    args = start._build_parser().parse_args(["--no-spreads"])
    active = start._active_services(args)
    assert "spreads" not in active and "approval" in active


def test_news_service_is_supervised_and_can_be_skipped():
    assert start.SERVICES["news"]["module"] == "scripts.run_news"
    args = start._build_parser().parse_args(["--no-news"])
    active = start._active_services(args)
    assert "news" not in active and "spreads" in active
