import math

import pytest

from scripts.prepare_equipment_catalog import build_catalog
from src.equipment_costs import estimate_equipment_cost, load_catalog


@pytest.fixture
def catalog():
    return load_catalog()


def test_ambiguous_component_quantity_never_multiplies_package_price(catalog):
    result = estimate_equipment_cost(catalog, [{"equipment_id": "6337"}])
    assert result["equipment_subtotal_krw"] == 3_270_000
    component = catalog["packages"]["6337"]["components_for_reference_only"][5]
    assert component["displayed_quantity"] == "3"
    assert component["displayed_price_krw"] == 120_000


def test_unknown_extras_do_not_look_like_final_capex(catalog):
    result = estimate_equipment_cost(catalog, [{"equipment_id": "5126"}])
    assert result["equipment_subtotal_krw"] == 20_903_000
    assert result["initial_capex_krw"] is None
    assert result["unresolved_cost_inputs"] == ["installation_krw", "additional_vat_krw"]
    assert not result["is_verified_quote"]


def test_options_are_explicit_and_scale_only_with_package_quantity(catalog):
    selection = [{"equipment_id": "6688", "quantity": 2, "option_ids": ["6688-option-2"]}]
    result = estimate_equipment_cost(catalog, selection, installation_krw=1_000_000, additional_vat_krw=0)
    assert result["equipment_subtotal_krw"] == 30_600_000
    assert result["initial_capex_krw"] == 31_600_000
    assert result["status"] == "planning_assumption"
    assert not result["is_verified_quote"]


def test_bundle_internals_and_unselected_options_not_added_again(catalog):
    result = estimate_equipment_cost(catalog, [{"equipment_id": "5126"}, {"equipment_id": "6688"}])
    assert result["equipment_subtotal_krw"] == 35_903_000
    assert catalog["packages"]["6688"]["published_options_total_krw"] == 28_400_000


@pytest.mark.parametrize("selections", [
    [], "6337", [None], [{"equipment_id": "missing"}],
    [{"equipment_id": "6337"}, {"equipment_id": "6337"}],
    [{"equipment_id": "6337", "quantity": 0}],
    [{"equipment_id": "6337", "quantity": True}],
    [{"equipment_id": "6337", "quantity": 1.5}],
    [{"equipment_id": "6337", "option_ids": "6337-option-1"}],
    [{"equipment_id": "6337", "option_ids": ["6688-option-1"]}],
    [{"equipment_id": "6337", "option_ids": ["6337-option-1", "6337-option-1"]}],
])
def test_invalid_selections_are_rejected(catalog, selections):
    with pytest.raises(ValueError):
        estimate_equipment_cost(catalog, selections)


@pytest.mark.parametrize("value", [-1, math.nan, math.inf, True, "1000"])
@pytest.mark.parametrize("field", ["installation_krw", "additional_vat_krw"])
def test_invalid_extra_costs_are_rejected(catalog, field, value):
    with pytest.raises(ValueError, match=field):
        estimate_equipment_cost(catalog, [{"equipment_id": "6337"}], **{field: value})


def test_explicit_zero_extra_cost_is_an_assumption_not_quote(catalog):
    result = estimate_equipment_cost(catalog, [{"equipment_id": "6337"}], installation_krw=0, additional_vat_krw=0)
    assert result["initial_capex_krw"] == 3_270_000
    assert not result["unresolved_cost_inputs"]
    assert not result["is_verified_quote"]


def test_builder_rejects_missing_package_total():
    record = {"equipment_id": "6337", "price_tables": [[["합계", "- 원"]], []]}
    with pytest.raises(ValueError, match="total missing"):
        build_catalog([record])
