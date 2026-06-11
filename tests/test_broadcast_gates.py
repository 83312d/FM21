"""Broadcast layer contract gates — nginx mounts, fm21.liq annotate, liquidsoap compile (U-TDD-2)."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
NGINX_GATEWAY_CONF = REPO_ROOT / "docker/nginx-gateway.conf"
FM21_LIQ = REPO_ROOT / "broadcast/liquidsoap/fm21.liq"
LIQUIDSOAP_CHECK_SCRIPT = REPO_ROOT / "scripts/liquidsoap_check.sh"

MOUNT_CITIES = ("moscow", "spb")


@pytest.fixture
def nginx_gateway_conf() -> str:
    return NGINX_GATEWAY_CONF.read_text(encoding="utf-8")


@pytest.fixture
def fm21_liq_source() -> str:
    return FM21_LIQ.read_text(encoding="utf-8")


def _mount_location_block(conf: str, city: str) -> str:
    pattern = rf"location\s*=\s*/{re.escape(city)}\s*\{{"
    match = re.search(pattern, conf)
    assert match, f"missing static location = /{city} in nginx gateway config"
    start = match.start()
    depth = 0
    for index in range(match.end() - 1, len(conf)):
        char = conf[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return conf[start : index + 1]
    raise AssertionError(f"unclosed location block for /{city}")


@pytest.mark.parametrize("city", MOUNT_CITIES)
def test_nginx_gateway_has_static_mount_location(nginx_gateway_conf: str, city: str) -> None:
    block = _mount_location_block(nginx_gateway_conf, city)
    assert f"proxy_pass http://icecast:8000/{city};" in block
    assert "$request_uri" not in block


def test_nginx_gateway_mount_proxy_pass_never_uses_request_uri(nginx_gateway_conf: str) -> None:
    for city in MOUNT_CITIES:
        block = _mount_location_block(nginx_gateway_conf, city)
        for line in block.splitlines():
            if "proxy_pass" in line:
                assert "$request_uri" not in line, (
                    f"/{city} proxy_pass must use a static upstream path, not $request_uri "
                    "(requires resolver and caused gateway 502 regressions)"
                )


def _news_pair_main_annotate_branch(source: str) -> str:
    marker = 'if type_ == "NEWS_PAIR" and part == "main" then'
    start = source.find(marker)
    assert start != -1, "annotated_request missing NEWS_PAIR main branch"
    else_pos = source.find("else", start)
    assert else_pos != -1, "annotated_request NEWS_PAIR main branch missing else"
    return source[start:else_pos]


def test_fm21_liq_news_pair_main_omits_duration_in_annotate(fm21_liq_source: str) -> None:
    branch = _news_pair_main_annotate_branch(fm21_liq_source)
    assert "request.create(" in branch
    assert 'duration="' not in branch
    assert "duration=" not in branch


def test_fm21_liq_basic_syntax_contract(fm21_liq_source: str) -> None:
    """Unit-tier gate: file shape and annotate contract without liquidsoap binary."""
    assert fm21_liq_source.startswith("#!/usr/bin/env liquidsoap\n")
    assert "def annotated_request(row)" in fm21_liq_source
    assert "def mount_city(city_tag)" in fm21_liq_source
    assert fm21_liq_source.rstrip().endswith("list.iter(mount_city, city_tags)")
    open_braces = fm21_liq_source.count("{")
    close_braces = fm21_liq_source.count("}")
    assert open_braces == close_braces, "unbalanced braces in fm21.liq"
    _news_pair_main_annotate_branch(fm21_liq_source)


def test_liquidsoap_integration_gate_documented_in_scripts() -> None:
    assert LIQUIDSOAP_CHECK_SCRIPT.is_file(), (
        "scripts/liquidsoap_check.sh must document the liquidsoap --check integration gate"
    )
    script = LIQUIDSOAP_CHECK_SCRIPT.read_text(encoding="utf-8")
    assert "liquidsoap" in script
    assert "--check" in script
    assert "fm21.liq" in script


@pytest.mark.integration
def test_fm21_liq_liquidsoap_check() -> None:
    liquidsoap_bin = os.environ.get("LIQUIDSOAP_BIN")
    if not liquidsoap_bin:
        pytest.skip(
            "LIQUIDSOAP_BIN not set; run "
            "docker compose run --rm --no-deps liquidsoap liquidsoap --check "
            "/broadcast/liquidsoap/fm21.liq or scripts/liquidsoap_check.sh"
        )
    fm21_path = os.environ.get("FM21_LIQ_PATH", str(FM21_LIQ))
    result = subprocess.run(
        [liquidsoap_bin, "--check", fm21_path],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"liquidsoap --check failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
