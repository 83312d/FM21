#!/usr/bin/env bash
# Executable mapping from spec/acceptance.yaml to Docker layer gates (U-TDD-5).
# Run from repo root:
#   bash scripts/verify_acceptance.sh --phase 1 --allow-manual
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PHASE=""
STRICT=0
ALLOW_MANUAL=0

usage() {
  cat <<'EOF'
Usage: scripts/verify_acceptance.sh --phase N [OPTIONS]

Run automated acceptance gates for FM21 phase N (1–5).

Options:
  --phase N         Phase number (1–5); runs non-deferred AEs for that phase
  --strict          Fail when manual verification bindings exist (no --allow-manual)
  --allow-manual    Permit manual-only AE bindings (warn instead of fail in --strict)
  -h, --help        Show this help

Gates:
  A — pytest        Phase-specific targets from spec/acceptance.yaml (or tests/)
  B — liquidsoap    docker compose run --rm --no-deps liquidsoap liquidsoap --check
  C — gateway       GET http://localhost:8080/moscow and /spb (skip if stack down)
  D — e2e           docker compose run --rm e2e when phase AEs list e2e bindings
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --phase)
      PHASE="${2:-}"
      shift 2
      ;;
    --strict)
      STRICT=1
      shift
      ;;
    --allow-manual)
      ALLOW_MANUAL=1
      shift
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      echo "verify_acceptance.sh: unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ -z "$PHASE" ]]; then
  echo "verify_acceptance.sh: --phase is required" >&2
  usage >&2
  exit 1
fi

if [[ ! "$PHASE" =~ ^[1-5]$ ]]; then
  echo "verify_acceptance.sh: --phase must be 1–5 (got: $PHASE)" >&2
  exit 1
fi

ACCEPTANCE_YAML="$ROOT/spec/acceptance.yaml"
if [[ ! -f "$ACCEPTANCE_YAML" ]]; then
  echo "verify_acceptance.sh: missing $ACCEPTANCE_YAML" >&2
  exit 1
fi

FAILED=0
SKIPPED=0

log_pass() { echo "[PASS] $*"; }
log_fail() { echo "[FAIL] $*"; FAILED=1; }
log_skip() { echo "[SKIP] $*"; SKIPPED=1; }
log_warn() { echo "[WARN] $*"; }

parse_acceptance_phase() {
  local phase="$1"
  if command -v python3 >/dev/null 2>&1 && python3 -c "import yaml" 2>/dev/null; then
    python3 - "$phase" "$ACCEPTANCE_YAML" <<'PY'
import sys
from pathlib import Path

import yaml

phase = int(sys.argv[1])
path = Path(sys.argv[2])
doc = yaml.safe_load(path.read_text(encoding="utf-8"))

pytest_targets: list[str] = []
e2e_targets: list[str] = []
manual_aes: list[str] = []
ae_ids: list[str] = []


def dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def normalize_target(value: str) -> str:
    return value.split(" (", 1)[0].strip()


def collect_binding(entry: object, ae_id: str) -> None:
    if isinstance(entry, str):
        if entry.startswith("pytest:"):
            target = normalize_target(entry.split(":", 1)[1])
            if target:
                pytest_targets.append(target)
        elif entry.startswith("e2e:"):
            target = normalize_target(entry.split(":", 1)[1])
            if target:
                e2e_targets.append(target)
        elif entry.startswith("manual:"):
            manual_aes.append(ae_id)
        return
    if not isinstance(entry, dict):
        return
    for key, value in entry.items():
        if not isinstance(value, str):
            continue
        if key == "pytest":
            target = normalize_target(value)
            if target:
                pytest_targets.append(target)
        elif key == "e2e":
            target = normalize_target(value)
            if target:
                e2e_targets.append(target)
        elif key == "manual":
            manual_aes.append(ae_id)


for ae in doc.get("acceptance", []):
    if ae.get("phase") != phase:
        continue
    if ae.get("deferred"):
        continue
    ae_id = str(ae.get("id", ""))
    ae_ids.append(ae_id)
    for entry in ae.get("verification", []):
        collect_binding(entry, ae_id)

import shlex

print("PYTEST_TARGETS=" + shlex.quote(" ".join(dedupe(pytest_targets))))
print("E2E_TARGETS=" + shlex.quote(" ".join(dedupe(e2e_targets))))
print("MANUAL_AES=" + shlex.quote(",".join(dedupe(manual_aes))))
print("AE_IDS=" + shlex.quote(",".join(ae_ids)))
PY
    return
  fi

  docker compose run --rm --no-deps -T test python - "$phase" <<'PY'
import sys
from pathlib import Path

import yaml

phase = int(sys.argv[1])
path = Path("spec/acceptance.yaml")
doc = yaml.safe_load(path.read_text(encoding="utf-8"))

pytest_targets: list[str] = []
e2e_targets: list[str] = []
manual_aes: list[str] = []
ae_ids: list[str] = []


def dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def normalize_target(value: str) -> str:
    return value.split(" (", 1)[0].strip()


def collect_binding(entry: object, ae_id: str) -> None:
    if isinstance(entry, str):
        if entry.startswith("pytest:"):
            target = normalize_target(entry.split(":", 1)[1])
            if target:
                pytest_targets.append(target)
        elif entry.startswith("e2e:"):
            target = normalize_target(entry.split(":", 1)[1])
            if target:
                e2e_targets.append(target)
        elif entry.startswith("manual:"):
            manual_aes.append(ae_id)
        return
    if not isinstance(entry, dict):
        return
    for key, value in entry.items():
        if not isinstance(value, str):
            continue
        if key == "pytest":
            target = normalize_target(value)
            if target:
                pytest_targets.append(target)
        elif key == "e2e":
            target = normalize_target(value)
            if target:
                e2e_targets.append(target)
        elif key == "manual":
            manual_aes.append(ae_id)


for ae in doc.get("acceptance", []):
    if ae.get("phase") != phase:
        continue
    if ae.get("deferred"):
        continue
    ae_id = str(ae.get("id", ""))
    ae_ids.append(ae_id)
    for entry in ae.get("verification", []):
        collect_binding(entry, ae_id)

import shlex

print("PYTEST_TARGETS=" + shlex.quote(" ".join(dedupe(pytest_targets))))
print("E2E_TARGETS=" + shlex.quote(" ".join(dedupe(e2e_targets))))
print("MANUAL_AES=" + shlex.quote(",".join(dedupe(manual_aes))))
print("AE_IDS=" + shlex.quote(",".join(ae_ids)))
PY
}

run_gate() {
  local name="$1"
  shift
  echo ""
  echo "==> Gate: $name"
  set +e
  "$@"
  local rc=$?
  set -e
  if [[ $rc -eq 0 ]]; then
    log_pass "$name"
    return 0
  fi
  log_fail "$name (exit $rc)"
  return 1
}

gateway_reachable() {
  curl -sf --max-time 2 -o /dev/null "http://localhost:8080/" 2>/dev/null
}

gateway_mount_ok() {
  local mount="$1"
  local code
  # ICY mounts stream forever; a short GET would time out and look like failure.
  code="$(
    curl -s -o /dev/null -w "%{http_code}" --max-time 5 \
      -H "Range: bytes=0-0" \
      "http://localhost:8080/${mount}" 2>/dev/null || true
  )"
  [[ "$code" == "200" ]]
}

echo "FM21 acceptance verification — phase ${PHASE}"
echo "spec: ${ACCEPTANCE_YAML}"

# shellcheck disable=SC2046
eval "$(parse_acceptance_phase "$PHASE")"

if [[ -n "${AE_IDS:-}" ]]; then
  echo "AEs: ${AE_IDS}"
else
  echo "AEs: (none — no non-deferred acceptance entries for phase ${PHASE})"
fi

if [[ -n "${MANUAL_AES:-}" ]]; then
  if [[ "$STRICT" -eq 1 && "$ALLOW_MANUAL" -eq 0 ]]; then
    echo ""
    echo "==> Gate: manual bindings"
    log_fail "manual bindings present (${MANUAL_AES}) — re-run with --allow-manual or drop --strict"
  elif [[ "$ALLOW_MANUAL" -eq 1 ]]; then
    echo ""
    echo "==> Gate: manual bindings"
    log_warn "manual verification deferred for: ${MANUAL_AES}"
    log_pass "manual bindings (--allow-manual)"
  else
    echo ""
    echo "==> Gate: manual bindings"
    log_warn "manual verification noted for: ${MANUAL_AES} (not required without --strict)"
    log_pass "manual bindings (informational)"
  fi
fi

# Gate A — pytest
PYTEST_ARGS=()
if [[ -n "${PYTEST_TARGETS:-}" ]]; then
  read -r -a PYTEST_ARGS <<< "${PYTEST_TARGETS}"
  echo ""
  echo "pytest targets: ${PYTEST_ARGS[*]}"
else
  PYTEST_ARGS=("tests/")
  echo ""
  echo "pytest targets: tests/ (no phase-specific pytest bindings)"
fi

run_gate "A — pytest" docker compose run --rm test pytest "${PYTEST_ARGS[@]}" -q

# Gate B — liquidsoap compile check
run_gate "B — liquidsoap --check" \
  docker compose run --rm --no-deps liquidsoap liquidsoap --check /broadcast/liquidsoap/fm21.liq

# Gate C — gateway mount smoke
echo ""
echo "==> Gate: C — gateway mounts"
if gateway_reachable; then
  GATE_C_OK=1
  for mount in moscow spb; do
    if gateway_mount_ok "$mount"; then
      log_pass "C — gateway GET /${mount} → 200"
    else
      log_fail "C — gateway GET /${mount} (expected HTTP 200)"
      GATE_C_OK=0
    fi
  done
  if [[ "$GATE_C_OK" -eq 0 ]]; then
    FAILED=1
  fi
else
  log_skip "C — gateway mounts (gateway not reachable at http://localhost:8080 — start stack with: docker compose up)"
fi

# Gate D — e2e (when phase lists e2e bindings)
# Phase 5 adds full-product smoke; geo-isolation runs without AE6 (60s flake).
if [[ -n "${E2E_TARGETS:-}" ]]; then
  echo ""
  if [[ "$PHASE" == "5" ]]; then
    echo "e2e bindings: ${E2E_TARGETS:-} (+ stream-playback + full-product smoke)"
    run_gate "D — e2e" docker compose --profile e2e run --rm e2e \
      npx vitest run tests/e2e/full-product.spec.ts tests/e2e/stream-playback.spec.ts \
        tests/e2e/geo-isolation.spec.ts \
      -t "health|geo|web client|sync radio|mounts|moscow|spb|AE4|happy path|AE-CITY|geo isolation|AE-NOW-PLAYING"
  else
    echo "e2e bindings: ${E2E_TARGETS:-} (+ stream-playback gate)"
    run_gate "D — e2e" docker compose --profile e2e run --rm e2e \
      npx vitest run tests/e2e/stream-playback.spec.ts tests/e2e/geo-isolation.spec.ts \
      -t "moscow|spb|AE4|happy path|AE-CITY|geo isolation|AE-NOW-PLAYING"
  fi
else
  echo ""
  echo "==> Gate: D — e2e"
  log_skip "D — e2e (no e2e bindings for phase ${PHASE})"
fi

echo ""
if [[ "$FAILED" -eq 0 ]]; then
  if [[ "$SKIPPED" -eq 1 ]]; then
    echo "Result: PASS (with skips)"
  else
    echo "Result: PASS"
  fi
  exit 0
fi

echo "Result: FAIL"
exit 1
