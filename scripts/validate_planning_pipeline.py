"""Audit real inputs, nested farm validation, and actual prediction-to-income runs."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.economics import evaluate_plan  # noqa: E402
from src.planning_models import (apply_prediction_to_plan, build_cohorts, digest,  # noqa: E402
                                 fit_candidate, predict_plan, validate_and_fit)  # noqa: E402
from src.price_forecast import run_price_experiment  # noqa: E402
from src.risk_simulation import simulate_plan  # noqa: E402


def verify_other_experiments() -> dict:
    """Recompute stored OOF scores, and rerun the price time-separated experiment."""
    checks = {}
    growth_metrics = json.loads((ROOT / "artifacts/inseason_metrics.json").read_text(encoding="utf-8"))
    growth_path = ROOT / "artifacts/inseason_oof_private.csv"
    if digest(growth_path) != growth_metrics["private_oof_sha256"]:
        raise ValueError("Growth OOF file integrity differs")
    growth = pd.read_csv(growth_path)
    for metric in growth_metrics["models"]:
        error = growth[metric["model"]] - growth["next_visit_height_mm"]
        np.testing.assert_allclose(float(error.abs().mean()), metric["mae_mm"], rtol=1e-10)
    if growth.groupby("farm_group").fold.nunique().max() != 1:
        raise ValueError("Growth facility appears in more than one held-out fold")
    checks["growth"] = {"status": "stored_scores_recomputed", "n": len(growth),
                         "groups": int(growth.farm_group.nunique()), "selection_used_same_oof": True,
                         "models": growth_metrics["models"]}
    price_path = ROOT / "data/processed/kamis_wholesale_monthly_kg.csv"
    old = json.loads((ROOT / "artifacts/price_forecast_metrics.json").read_text(encoding="utf-8"))
    if digest(price_path) != old["input_sha256"]:
        raise ValueError("Price input differs from frozen experiment")
    current = run_price_experiment(pd.read_csv(price_path))["summary"]
    for name in ["holdout_selected", "holdout_baseline"]:
        np.testing.assert_allclose(current[name]["mae_krw_per_kg"], old[name]["mae_krw_per_kg"], rtol=1e-10)
    checks["price"] = {"status": "time_separated_experiment_rerun", "split": current["split"],
                        "holdout_selected": current["holdout_selected"], "holdout_baseline": current["holdout_baseline"]}
    return checks


def main() -> None:
    private = ROOT / "artifacts/planning_validation"
    private.mkdir(parents=True, exist_ok=True)
    reports = ROOT / "reports"
    cohorts, audit = build_cohorts(ROOT)
    (private / "data_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    models = {}
    for target, rows in cohorts.items():
        print(f"Validating {target}: {len(rows)} cycles, {rows.group.nunique()} facilities", flush=True)
        bundle, oof = validate_and_fit(rows, target)
        oof.to_csv(private / f"{target}_oof_private.csv", index=False, encoding="utf-8-sig")
        bundle["source_sha256"] = audit["source_sha256"]
        bundle["training_rows"] = len(rows)
        bundle["training_facilities"] = int(rows.group.nunique())
        bundle["validation"]["oof_sha256"] = digest(private / f"{target}_oof_private.csv")
        models[target] = bundle
        print(f"Selected {target}: {bundle['portable']['model']}; nested MAE {bundle['validation']['metrics']['nested_selection']['mae']:.3f}", flush=True)
    other = verify_other_experiments()
    examples = []
    inference_checks = []
    original = json.loads((ROOT / "artifacts/planning_demo.json").read_text(encoding="utf-8"))["inputs"]
    for target, bundle in models.items():
        rows = cohorts[target].loc[cohorts[target].crop.eq("딸기")]
        typical = rows.groupby(["variety", "region", "district", "facility_type"]).size().idxmax()
        query = dict(zip(["variety", "region", "district", "facility_type"], typical))
        query.update(crop="딸기", area_m2=1000, planting_year=2027, planting_month=9)
        bundle["example_query"] = query
        native = fit_candidate(cohorts[target], bundle["portable"]["model"])
        checks = [{**query, "area_m2": area} for area in [500, 1000, 2000, 9916.99999999, 13222.50000001]]
        for check in checks:
            expected_native = float(native.predict(pd.DataFrame([check]))[0])
            np.testing.assert_allclose(predict_plan(bundle, check)["prediction"], expected_native, rtol=2e-6, atol=.1)
            inference_checks.append({"target": target, "query": check, "expected_native_prediction": expected_native})
        prediction = predict_plan(bundle, query)
        payload = apply_prediction_to_plan(original, prediction, acknowledge_period=True)
        result = evaluate_plan(payload)
        risk = simulate_plan(payload, {"yield": .1, "price": .2, "cash_cost": .1}, n_samples=2000, scenario_index=1)
        base = result["scenarios"][1]
        expected = prediction["prediction"] if target == "revenue" else prediction["prediction"] * payload["benchmark"]["farmgate_price_krw_per_kg"]
        np.testing.assert_allclose(base["annual_revenue_krw"], expected, rtol=1e-10)
        examples.append({"target": target, "inputs": payload, "results": result, "sensitivity_quantiles": risk["quantiles"]})
        print(f"Connected {target}: predicted {prediction['prediction']:.2f}; annual revenue {base['annual_revenue_krw']:.2f}", flush=True)
    stamp = datetime.now(timezone.utc).isoformat()
    code_hashes = {name: digest(ROOT / name) for name in ["src/planning_models.py", "src/economics.py", "scripts/validate_planning_pipeline.py"]}
    model_file = reports / "planning_models.json"
    model_file.write_text(json.dumps({"schema_version": 1, "generated_at_utc": stamp, "models": models}, ensure_ascii=False, indent=2), encoding="utf-8")
    (reports / "planning_inference_checks.json").write_text(json.dumps(inference_checks, ensure_ascii=False, indent=2), encoding="utf-8")
    rda = pd.read_csv(ROOT / "data/processed/rda_crop_income.csv")
    latest = rda.loc[rda.year.eq(rda.year.max()) & rda.region.eq("전국")]
    reference_columns = ["crop", "crop_original", "cultivation_type", "source_category", "year", "period_basis",
                         "yield_kg_per_1000m2", "farmgate_price_krw_per_kg", "operating_cost_krw_per_1000m2",
                         "depreciation_krw_per_1000m2", "family_labor_cost_krw_per_1000m2", "source_url", "source_page"]
    latest = latest.assign(source_category=latest.crop_original)
    references = latest[reference_columns].to_dict("records")
    (reports / "planning_cost_references.json").write_text(json.dumps(references, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    summary = {"generated_at_utc": stamp, "source_integrity_checked": True,
               "cohort_policy": audit["policy"], "target_period_confirmed": False,
               "cohorts": {target: {"primary_rows": audit[target]["primary_rows"],
                                     "training_rows": bundle["training_rows"],
                                     "training_facilities": bundle["training_facilities"],
                                     "quarantined_rows": len(audit[target]["quarantined_ids"]),
                                     "selected_model": bundle["portable"]["model"],
                                     "validation": bundle["validation"]} for target, bundle in models.items()},
               "other_experiments": other,
               "models_sha256": digest(model_file), "code_sha256": code_hashes, "examples": examples,
               "connection_status": "Actual fitted model -> plan -> economics -> 2000 sensitivity runs verified",
               "external_or_prospective_validation_completed": False,
               "dsz_actual_data_available_locally": False}
    (reports / "planning_validation_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Completed real-data validation and financial connection", flush=True)


if __name__ == "__main__":
    main()
