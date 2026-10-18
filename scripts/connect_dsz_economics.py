"""Connect approved offline DSZ predictions to explicit matching annual plans."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.economics import evaluate_plan  # noqa: E402
from src.planning_models import apply_prediction_to_plan, dsz_prediction_for_plan, digest  # noqa: E402
from src.dsz_period import require_model_confirmation  # noqa: E402


def connect_files(predictions_path: Path, plans_path: Path, costs: dict,
                  *, assume_one_cycle: bool) -> list[dict]:
    """Bind the forecast to the exact original plan features using its sidecar."""
    sidecar = predictions_path.with_suffix(".provenance.json")
    provenance = json.loads(sidecar.read_text(encoding="utf-8"))
    if digest(predictions_path) != provenance["prediction_sha256"]:
        raise ValueError("DSZ prediction hash differs from provenance")
    if digest(plans_path) != provenance["plans_sha256"]:
        raise ValueError("DSZ plans hash differs from the forecast's original features")
    predictions = pd.read_csv(predictions_path, dtype={"plan_id": str}, keep_default_na=False)
    plans = pd.read_csv(plans_path, dtype={"plan_id": str}, keep_default_na=False)
    if len(predictions) != provenance["rows"]:
        raise ValueError("DSZ prediction count differs from provenance")
    plans = plans.copy()
    plans["plan_id"] = plans.plan_id.astype(str) if "plan_id" in plans else [str(index) for index in range(len(plans))]
    if plans.plan_id.duplicated().any():
        raise ValueError("Each planned feature row needs a unique plan_id")
    if predictions.duplicated(["plan_id", "target"]).any():
        raise ValueError("Ambiguous duplicate plan/target prediction")
    results = []
    indexed = plans.set_index("plan_id")
    for row in predictions.to_dict("records"):
        require_model_confirmation({**row, "target_period_confirmation": provenance.get("target_period_confirmation"),
                                    "training_cohort": provenance.get("training_cohort")})
        if row["target_period_evidence_sha256"] != provenance.get("target_period_evidence_sha256"):
            raise ValueError("DSZ prediction period evidence differs from provenance")
        if row["training_cohort_sha256"] != provenance.get("training_cohort_sha256"):
            raise ValueError("DSZ prediction training cohort differs from provenance")
        plan_id = str(row["plan_id"])
        if plan_id not in indexed.index or plan_id not in costs:
            raise ValueError("Every prediction needs matching features and an explicit cost plan")
        features = indexed.loc[plan_id].to_dict()
        payload = costs[plan_id]
        if payload.get("reference", {}).get("crop") != features["crop"]:
            raise ValueError("Financial crop differs from the model's planned crop")
        prediction = dsz_prediction_for_plan(row, features)
        # The legacy adapter deliberately cannot certify periods. Preserve only
        # the document-backed review validated at this CLI boundary.
        prediction.update(target_period_confirmed=True,
                          target_period_evidence_sha256=row["target_period_evidence_sha256"],
                          training_cohort_sha256=row["training_cohort_sha256"],
                          period_confirmation_level="documented_review_not_independent_provider_verification")
        bridged = apply_prediction_to_plan(payload, prediction, acknowledge_period=assume_one_cycle)
        results.append({"plan_id": plan_id, "target": prediction["target"], "inputs": bridged,
                        "results": evaluate_plan(bridged), "data_kind": prediction["data_kind"]})
        results[-1]["dsz_provenance_sha256"] = digest(sidecar)
        results[-1]["prediction_inputs_provenance"] = provenance
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--plans", type=Path, required=True)
    parser.add_argument("--cost-plans", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--assume-one-cycle-per-year", action="store_true")
    args = parser.parse_args()
    records = connect_files(args.predictions, args.plans,
                            json.loads(args.cost_plans.read_text(encoding="utf-8")),
                            assume_one_cycle=args.assume_one_cycle_per_year)
    for record in records:
        record["cost_plans_sha256"] = digest(args.cost_plans)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(records, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(f"Connected {len(records)} plan/target predictions; source kind retained")


if __name__ == "__main__":
    main()
