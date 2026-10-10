"""Seeded assumption sensitivity, not a fitted stochastic crop or return model."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np

from src.economics import evaluate_plan

OUTPUTS = ["annual_yield_kg", "annual_revenue_krw", "annual_cash_operating_cost_krw",
           "annual_income_before_family_labor_krw", "annual_income_after_family_labor_krw",
           "npv_krw", "undiscounted_balance_krw", "required_annual_yield_for_horizon_payback_kg"]
MULTIPLIERS = {"yield": "yield_multiplier", "price": "price_multiplier", "cash_cost": "cash_cost_multiplier"}


def simulate_plan(
    payload: Mapping[str, Any], uncertainty: Mapping[str, float], *,
    n_samples: int = 2000, seed: int = 42, scenario_index: int = 0,
) -> dict[str, Any]:
    """Apply independent symmetric triangular factors to one explicit scenario.

    A half-width of .2 means factors in [.8, 1.2], mode 1. A single draw is held
    constant over the investment horizon. Existing-operation retrofit baselines,
    depreciation, capex, replacements and discount rates remain fixed. The
    resulting quantiles describe these assumptions, not calibrated probabilities.
    """
    evaluated = evaluate_plan(payload)
    if isinstance(n_samples, bool) or not isinstance(n_samples, int) or not 1 <= n_samples <= 20000:
        raise ValueError("n_samples must be a whole number between 1 and 20000")
    if isinstance(scenario_index, bool) or not isinstance(scenario_index, int) or not 0 <= scenario_index < len(evaluated["scenarios"]):
        raise ValueError("scenario_index must select an existing scenario")
    if set(uncertainty) != set(MULTIPLIERS):
        raise ValueError("Explicit yield, price and cash_cost half-widths are required")
    widths = {}
    for key, value in uncertainty.items():
        if isinstance(value, bool) or not np.isfinite(float(value)) or not 0 <= float(value) <= 1:
            raise ValueError("Uncertainty half-widths must be finite numbers between 0 and 1")
        widths[key] = float(value)
    rng = np.random.default_rng(seed)
    factors = {key: np.ones(n_samples) if width == 0 else rng.triangular(1 - width, 1, 1 + width, n_samples)
               for key, width in widths.items()}
    center = dict(payload["scenarios"][scenario_index])
    draws = [{**center, "name": f"assumption_draw_{index + 1}",
              **{name: float(center[name]) * factors[key][index] for key, name in MULTIPLIERS.items()}}
             for index in range(n_samples)]
    results = evaluate_plan({**payload, "scenarios": draws})["scenarios"]
    samples = [{**{key: row[key] for key in OUTPUTS}, "payback_year": row["payback_year"]}
               for row in results]
    quantiles = {}
    for key in OUTPUTS:
        values = np.array([row[key] for row in samples if row[key] is not None], dtype=float)
        quantiles[key] = None if not len(values) else dict(zip(["p05", "p50", "p95"], map(float, np.quantile(values, [.05, .5, .95]))))
    return {"deterministic": evaluated["scenarios"][scenario_index], "quantiles": quantiles,
            "samples": samples, "assumptions": {
                "distribution": "independent symmetric triangular multipliers centered at 1",
                "relative_half_widths": widths, "n_samples": n_samples, "seed": seed,
                "correlation": "Independent yield/price/cash-cost factors; no estimated correlations",
                "time_behavior": "Each draw remains constant over the full horizon, not independent annual shocks",
                "fixed_inputs": "Capex, depreciation, baseline existing-operation cash flow, replacements and discount rate",
                "interpretation": "Assumption-distribution percentiles, NOT calibrated confidence intervals or success probabilities",
                "bep_definition": "Annual kg needed for undiscounted payback by the chosen horizon; family labor is separate",
                "exclusions": evaluated["exclusions"],
            }}
