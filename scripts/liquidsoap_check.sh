#!/usr/bin/env bash
# Layer gate: compile-check broadcast/liquidsoap/fm21.liq (U-TDD-2, plan 003).
# Run from repo root via Docker (ADR-003):
#   docker compose run --rm --no-deps liquidsoap liquidsoap --check /broadcast/liquidsoap/fm21.liq
set -euo pipefail
exec liquidsoap --check /broadcast/liquidsoap/fm21.liq
