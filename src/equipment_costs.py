"""Published equipment-package prices with explicit, separate extra-cost inputs."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from numbers import Real
from pathlib import Path
from typing import Any

DEFAULT_CATALOG = Path(__file__).resolve().parents[1] / "data/processed/equipment_catalog.json"


def load_catalog(path: str | Path | None = None) -> dict[str, Any]:
    """Read the prepared public-price catalog; it contains no farm records."""
    with Path(path or DEFAULT_CATALOG).open(encoding="utf-8") as stream:
        return json.load(stream)


def _amount(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a number")
    amount = float(value)
    if not math.isfinite(amount) or amount < 0:
        raise ValueError(f"{name} must be finite and nonnegative")
    return amount


def estimate_equipment_cost(
    catalog: Mapping[str, Any],
    selections: Sequence[Mapping[str, Any]],
    *,
    installation_krw: float | None = None,
    additional_vat_krw: float | None = None,
) -> dict[str, Any]:
    """Price packages and selected options, each option once per package unit.

    ``installation_krw`` and ``additional_vat_krw`` are *additional* amounts for
    the whole selection, not rates. None means unresolved; explicit zero means
    the user assumes no additional charge. No tax/installation inclusion is
    inferred from published prices, and no plant/building cost is added.
    """
    if isinstance(selections, (str, bytes)) or not isinstance(selections, Sequence) or not selections:
        raise ValueError("selections must contain at least one package")
    lines = []
    seen = set()
    for selection in selections:
        if not isinstance(selection, Mapping):
            raise ValueError("Each selection must be a mapping")
        equipment_id = selection.get("equipment_id")
        if not isinstance(equipment_id, str) or equipment_id not in catalog["packages"]:
            raise ValueError(f"Unknown equipment_id: {equipment_id!r}")
        if equipment_id in seen:
            raise ValueError("Duplicate equipment_id; use quantity instead")
        seen.add(equipment_id)
        quantity = selection.get("quantity", 1)
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
            raise ValueError("quantity must be a positive integer")
        package = catalog["packages"][equipment_id]
        option_ids = selection.get("option_ids", [])
        if not isinstance(option_ids, (list, tuple)) or any(not isinstance(item, str) for item in option_ids):
            raise ValueError("option_ids must be a list of option identifiers")
        if len(set(option_ids)) != len(option_ids):
            raise ValueError("Duplicate option_id")
        options = {option["option_id"]: option for option in package["options"]}
        if any(option_id not in options for option_id in option_ids):
            raise ValueError("Unknown option_id for selected package")
        base_price = _amount(package["package_price_krw"], "package_price_krw")
        options_price = sum(_amount(options[item]["price_krw"], "option price") for item in option_ids)
        lines.append({
            "equipment_id": equipment_id,
            "name": package["name"],
            "quantity": quantity,
            "option_ids": list(option_ids),
            "package_price_krw": base_price,
            "options_price_per_package_krw": options_price,
            "line_total_krw": quantity * (base_price + options_price),
            "source_url": package["source_url"],
            "checked_date": package["checked_date"],
        })
    installation = None if installation_krw is None else _amount(installation_krw, "installation_krw")
    vat = None if additional_vat_krw is None else _amount(additional_vat_krw, "additional_vat_krw")
    subtotal = sum(line["line_total_krw"] for line in lines)
    unresolved = [name for name, value in (("installation_krw", installation), ("additional_vat_krw", vat)) if value is None]
    return {
        "lines": lines,
        "equipment_subtotal_krw": subtotal,
        "installation_krw": installation,
        "additional_vat_krw": vat,
        "initial_capex_krw": None if unresolved else subtotal + installation + vat,
        "unresolved_cost_inputs": unresolved,
        "status": "incomplete_extra_costs" if unresolved else "planning_assumption",
        "is_verified_quote": False,
        "scope": "선택 장비와 명시한 설치비·추가 부가세만 포함. 온실 신축·토목·기타 설비·호환성 검토는 별도.",
        "limitations": list(catalog["limitations"]),
    }
