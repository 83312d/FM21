"""Acceptance spec structure — TZ §12 traceability and AE7–AE9 (U34)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
ACCEPTANCE_YAML = REPO_ROOT / "spec" / "acceptance.yaml"

TZ_SECTION_12_AREAS = (
    "Геотаргетинг",
    "Веб-клиент",
    "Фон",
    "Новости",
    "Музыка",
    "Объявления",
    "Бот",
    "Очередь",
    "Интеграции",
)

REQUIRED_AE_IDS = (
    "AE1",
    "AE2",
    "AE3",
    "AE4",
    "AE5",
    "AE6",
    "AE7",
    "AE8",
    "AE9",
)


@pytest.fixture
def acceptance_doc() -> dict:
    return yaml.safe_load(ACCEPTANCE_YAML.read_text(encoding="utf-8"))


def test_acceptance_yaml_has_tz_section_12_traceability(acceptance_doc: dict) -> None:
    rows = acceptance_doc.get("tz_section_12")
    assert isinstance(rows, list), "tz_section_12 must be a list"
    areas = [row["area"] for row in rows]
    assert areas == list(TZ_SECTION_12_AREAS), (
        f"tz_section_12 areas must match TZ §12 table order: {TZ_SECTION_12_AREAS}"
    )
    for row in rows:
        assert row.get("criterion"), f"missing criterion for {row.get('area')}"
        assert row.get("aes"), f"missing aes for {row.get('area')}"
        assert row.get("verification"), f"missing verification for {row.get('area')}"


def test_ae7_ae8_ae9_present_and_not_deferred(acceptance_doc: dict) -> None:
    by_id = {ae["id"]: ae for ae in acceptance_doc.get("acceptance", [])}
    for ae_id in ("AE7", "AE8", "AE9"):
        assert ae_id in by_id, f"{ae_id} missing from acceptance"
        assert by_id[ae_id].get("deferred") is not True, f"{ae_id} must not be deferred"


def test_ae5_not_deferred_with_automated_bindings(acceptance_doc: dict) -> None:
    by_id = {ae["id"]: ae for ae in acceptance_doc.get("acceptance", [])}
    ae5 = by_id["AE5"]
    assert ae5.get("deferred") is not True
    verification = ae5.get("verification", [])
    joined = " ".join(str(v) for v in verification)
    assert "test_bot_order" in joined
    assert "test_dequeue_priority" in joined


def test_all_required_ae_ids_exist(acceptance_doc: dict) -> None:
    ids = {ae["id"] for ae in acceptance_doc.get("acceptance", [])}
    for ae_id in REQUIRED_AE_IDS:
        assert ae_id in ids, f"{ae_id} missing from acceptance"
