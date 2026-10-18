"""Offline cycle-total shipment updates with documented labels and cutoff-safe inputs."""

from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer

from scripts.train_dsz import read_data
from src.dsz_data import ISSUE_COLUMNS, parse_date
from src.dsz_model import CATEGORICAL, FEATURES, METHODS, NUMERIC, features, fit_cpu, grouped_folds, prepare_target, scores, sha256
from src.dsz_observations import OBSERVATION_NUMERIC, build_observation_features, load_observation_tables
from src.dsz_period import evidence_digest, require_confirmed_rows, require_model_confirmation

ROOT = Path(__file__).resolve().parents[1]
IDENTITY = ["row_id", "facility_id", "cycle_id"]
LABEL = "reported_shipment_kg"
SCOPE = "inseason_cycle_total"
SOURCE_FILES = ["src/dsz_inseason.py", "src/dsz_observations.py", "src/dsz_model.py",
                "src/dsz_period.py", "src/dsz_data.py", "scripts/train_dsz.py",
                "scripts/run_dsz_inseason.py", "config/dsz_schema.json"]
LIMITATIONS = [
    "Synthetic data demonstrate execution only, never actual farm predictive accuracy.",
    "Cycle labels require document-backed period review; this is not independent provider verification.",
    "Only same-facility, uniquely matched cycle observations at or before the fixed cutoff are used.",
    "Observation availability at the historical prediction time is not independently verified; this is retrospective evaluation.",
    "Facility-group OOF scores select a model and are not an untouched final test.",
    "Latest-year checks report fixed candidates separately, never an independent score of the full-data OOF winner.",
    "The target is whole-cycle shipment kg, not remaining shipment, profit, payback or equipment impact.",
    "Sensor row counts do not increase the number of independent training facilities or cycles.",
]


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def source_hashes() -> dict:
    return {name: sha256(ROOT / name) for name in SOURCE_FILES}


def verify_raw_sources(sources: list[dict], manifest: dict) -> None:
    """A prepared label and observation summary must originate from the same export."""
    def identities(items):
        return sorted((item["dataset"], item["file"], item["sha256"]) for item in items)
    if identities(sources) != identities(manifest.get("sources", [])):
        raise ValueError("Raw source files/SHA differ from the preparation manifest; prepare again")


def model_features(rows: pd.DataFrame, extended: bool) -> pd.DataFrame:
    """Explicit whitelist: identities, outcomes, raw JSON and dates never enter X."""
    x = features(rows)
    if extended:
        if missing := set(OBSERVATION_NUMERIC) - set(rows.columns):
            raise ValueError(f"Missing observation feature columns: {sorted(missing)}")
        observations = rows[OBSERVATION_NUMERIC].apply(pd.to_numeric, errors="raise").astype(float)
        if np.isinf(observations.to_numpy()).any():
            raise ValueError("Observation features cannot contain infinity")
        x = pd.concat([x, observations], axis=1)
    return x


class TrainFoldModel:
    """Learn imputation statistics only from the current training fold."""

    def __init__(self, method: str, extended: bool):
        self.method = method
        self.extended = extended

    def fit(self, rows: pd.DataFrame, y):
        x = model_features(rows, self.extended)
        self.imputer = None
        if self.extended and self.method in {"catboost", "xgboost"}:
            numeric = NUMERIC + OBSERVATION_NUMERIC
            self.imputer = SimpleImputer(strategy="median", add_indicator=True, keep_empty_features=True)
            values = self.imputer.fit_transform(x[numeric])
            self.numeric_features = self.imputer.get_feature_names_out(numeric).tolist()
            x = pd.concat([x[CATEGORICAL], pd.DataFrame(values, index=x.index, columns=self.numeric_features)], axis=1)
            self.model, self.fallback = fit_cpu(self.method, x, y, numeric_features=self.numeric_features)
        else:
            # Both median comparators deliberately ignore observation features.
            self.model, self.fallback = fit_cpu(self.method, x[FEATURES], y)
        return self

    def predict(self, rows: pd.DataFrame):
        x = model_features(rows, self.extended)
        if self.imputer is not None:
            values = self.imputer.transform(x[NUMERIC + OBSERVATION_NUMERIC])
            x = pd.concat([x[CATEGORICAL], pd.DataFrame(values, index=x.index, columns=self.numeric_features)], axis=1)
        else:
            x = x[FEATURES]
        values = np.maximum(np.asarray(self.model.predict(x), dtype=float), 0)
        if not np.isfinite(values).all():
            raise ValueError("Nonfinite shipment predictions")
        return values


def matched_provenance(provenance: dict, rows: pd.DataFrame) -> dict:
    """Narrow the period declaration to the actual matched modelling cohort."""
    keys = set(zip(rows.facility_id, rows.cycle_id, strict=True))
    declaration = {**provenance["target_period_confirmation"], "cycles": [cycle for cycle in
        provenance["target_period_confirmation"]["cycles"] if (cycle["facility_id"], cycle["cycle_id"]) in keys]}
    original = provenance["training_cohort"]
    removed = original["used_rows"] - len(rows)
    cohort = {**original, "used_rows": len(rows),
              "confirmed_ineligible_excluded_rows": original["confirmed_ineligible_excluded_rows"] + removed,
              "inseason_additional_excluded_rows": removed,
              "eligibility_definition": "confirmed shipment, selected crop, valid cutoff and linked observations",
              "used_candidates": rows[IDENTITY + ["target_period_evidence_sha256"]].to_dict("records")}
    result = {**provenance, "target_period_confirmation": declaration,
              "target_period_evidence_sha256": evidence_digest(declaration),
              "training_cohort": cohort, "training_cohort_sha256": evidence_digest(cohort)}
    require_model_confirmation(result)
    return result


def join_training_rows(candidates: pd.DataFrame, observation_rows: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    if observation_rows.duplicated(IDENTITY).any() or observation_rows.row_id.duplicated().any():
        raise ValueError("Observation builder returned duplicate request identities")
    candidate_keys = set(map(tuple, candidates[IDENTITY].to_numpy()))
    if not set(map(tuple, observation_rows[IDENTITY].to_numpy())).issubset(candidate_keys):
        raise ValueError("Observation builder returned a different facility/cycle")
    joined = candidates.merge(observation_rows, on=IDENTITY, how="inner", validate="one_to_one", suffixes=("", "_observation"))
    for name in FEATURES:
        left, right = joined[name], joined[f"{name}_observation"]
        same = np.isclose(pd.to_numeric(left), pd.to_numeric(right), rtol=0, atol=1e-9) if name in NUMERIC else left.eq(right)
        if not np.all(same):
            raise ValueError(f"Prepared/raw facility feature mismatch: {name}")
    if not joined.has_observations.isin([True, False]).all():
        raise ValueError("Observation presence must be explicitly boolean")
    missing = joined.loc[~joined.has_observations, IDENTITY].to_dict("records")
    for item in missing:
        item["reason"] = "no_usable_observation_before_cutoff"
    joined = joined.loc[joined.has_observations].drop(columns=[f"{name}_observation" for name in FEATURES])
    return joined.sort_values("row_id").reset_index(drop=True), missing


def compare_models(rows: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    require_confirmed_rows(rows)
    folds = grouped_folds(rows)
    oof = rows[IDENTITY + ["as_of", LABEL]].copy()
    oof["fold"] = -1
    records, fallback_records = [], []
    for number, (training, query) in enumerate(folds):
        records.append({"fold": number, "train_row_ids": rows.iloc[training].row_id.tolist(),
                        "test_row_ids": rows.iloc[query].row_id.tolist(),
                        "train_facilities": int(rows.iloc[training].facility_id.nunique()),
                        "test_facilities": int(rows.iloc[query].facility_id.nunique()), "facility_overlap": False})
        oof.loc[query, "fold"] = number
        for mode in ["baseline", "extended"]:
            for method in METHODS:
                model = TrainFoldModel(method, extended=mode == "extended").fit(rows.iloc[training], rows.iloc[training][LABEL])
                oof.loc[query, f"{mode}__{method}"] = model.predict(rows.iloc[query])
                if model.fallback:
                    fallback_records.append({"fold": number, "mode": mode, "method": method, "reason": model.fallback})
    metrics = {mode: {method: {**scores(rows[LABEL], oof[f"{mode}__{method}"]),
                "by_fold": {str(number): scores(group[LABEL], group[f"{mode}__{method}"])
                            for number, group in oof.groupby("fold")}}
              for method in METHODS} for mode in ["baseline", "extended"]}
    selected = {mode: min(METHODS, key=lambda method: metrics[mode][method]["mae"]) for mode in metrics}
    return oof, {"models": metrics, "selected_methods": selected, "folds": records,
                 "same_rows_and_folds_for_all_candidates": True, "constant_training_fallbacks": fallback_records,
                 "selection": "lowest facility-group OOF MAE; model-selection evidence, not untouched final-test accuracy"}


def label_available_after(row: pd.Series) -> datetime | None:
    """Daily outcome dates are usable only after every selected survey day ends."""
    try:
        end_value = json.loads(row["target_period_evidence_json"])["cycle"]["end"]
        end = datetime.strptime(end_value, "%Y-%m-%d")
        surveys = json.loads(row["management_raw_json"])
        if not isinstance(surveys, list) or not surveys:
            return None
        dates = [end]
        for survey in surveys:
            value = survey.get("EXMN_YMD") if isinstance(survey, dict) else None
            observed = parse_date(value, compact=True) if isinstance(value, str) else None
            if observed is None:
                return None
            dates.append(observed)
        return max(dates) + timedelta(days=1)
    except (KeyError, TypeError, ValueError, OverflowError):
        return None


def latest_year_check(rows: pd.DataFrame) -> dict:
    """Fixed candidate temporal checks; do not call the OOF winner independently tested."""
    years = sorted(rows.planned_start_year.unique())
    if len(years) < 2:
        return {"status": "skipped", "reason": "Only one start year in the matched cohort"}
    query = rows.loc[rows.planned_start_year.eq(years[-1])]
    cutoff = pd.to_datetime(query.as_of).min()
    earlier = rows.loc[rows.planned_start_year.lt(years[-1])]
    training_indices, exclusions = [], []
    query_facilities = set(query.facility_id)
    for index, row in earlier.iterrows():
        available = label_available_after(row)
        reason = None
        if row.facility_id in query_facilities:
            reason = "facility_present_in_test"
        elif available is None:
            reason = "missing_or_invalid_label_availability_date"
        elif available > cutoff:
            reason = "label_not_available_by_test_cutoff"
        if reason:
            exclusions.append({**{key: row.get(key, "") for key in IDENTITY}, "reason": reason,
                               "label_available_after": available.isoformat() if available else None})
        else:
            training_indices.append(index)
    training = rows.loc[training_indices]
    temporal_audit = {
        "first_test_cutoff": cutoff.isoformat(), "earlier_candidate_rows": len(earlier),
        "excluded_training_rows": len(exclusions), "training_exclusions": exclusions,
        "exclusion_counts": {name: int(count) for name, count in
                             pd.Series([item["reason"] for item in exclusions], dtype=str).value_counts().items()},
        "label_availability_rule": "max(cycle end + 1 day, every selected EXMN_YMD + 1 day) <= first test cutoff",
        "label_availability_limitation": "Survey dates bound retrospective label availability; actual publication/loading time is not independently verified",
    }
    if training.empty or training.facility_id.nunique() < 2:
        return {"status": "skipped", "reason": "Fewer than two earlier completed training facilities after excluding test facilities",
                "test_year": int(years[-1]), "train_rows": len(training), "test_rows": len(query), **temporal_audit}
    results = {}
    for mode in ["baseline", "extended"]:
        results[mode] = {}
        for method in METHODS:
            model = TrainFoldModel(method, mode == "extended").fit(training, training[LABEL])
            results[mode][method] = {**scores(query[LABEL], model.predict(query)), "fallback": model.fallback}
    return {"status": "completed", "test_year": int(years[-1]), **temporal_audit,
            "train_row_ids": training.row_id.tolist(), "test_row_ids": query.row_id.tolist(),
            "facility_overlap": False, "models": results,
            "interpretation": "Fixed-candidate retrospective future-year comparison; not a final test of the full-data OOF-selected model"}


def train_inseason(data_dir: Path, input_dir: Path, output_dir: Path, *, cutoff_days: int = 30,
                   window_days: int = 28, crop: str = "딸기", encoding: str = "utf-8-sig") -> dict:
    if output_dir.exists():
        raise FileExistsError("Output directory already exists; choose a new run directory")
    if cutoff_days < 1 or window_days < 1 or not crop.strip():
        raise ValueError("Positive cutoff/window days and a crop are required")
    output_dir.mkdir(parents=True)
    metrics_path = output_dir / "dsz_inseason_metrics.json"
    try:
        candidates, provenance, manifest = read_data(data_dir)
        if manifest["schema_sha256"] != sha256(ROOT / "config/dsz_schema.json"):
            raise ValueError("Preparation schema differs from the current observation schema")
        shipment = prepare_target(candidates, "shipment")
        scope_exclusions = [{**row, "reason": "shipment_ineligible" if not row["shipment_eligible"] else "outside_selected_crop"}
                            for row in candidates.loc[~candidates.shipment_eligible | ~candidates.crop.eq(crop),
                                IDENTITY + ["crop", "shipment_eligible"]].to_dict("records")]
        shipment = shipment.loc[shipment.crop.eq(crop)].reset_index(drop=True)
        if shipment.empty:
            raise ValueError("No confirmed eligible shipment rows for the selected crop")
        tables, sources, validation = load_observation_tables(input_dir, encoding=encoding)
        verify_raw_sources(sources, manifest)
        observation_rows, audit = build_observation_features(tables, shipment[IDENTITY], cutoff_days, window_days)
        rows, no_observation = join_training_rows(shipment, observation_rows)
        audit = {**audit, "no_observation_exclusions": no_observation,
                 "scope_exclusions": scope_exclusions,
                 "confirmed_shipment_rows": len(shipment), "matched_rows": len(rows),
                 "matched_facilities": int(rows.facility_id.nunique()), "raw_sources": sources}
        write_json(output_dir / "observation_audit.json", audit)
        pd.DataFrame(validation, columns=ISSUE_COLUMNS).to_csv(output_dir / "observation_validation.csv", index=False, encoding="utf-8-sig")
        if rows.facility_id.nunique() < 2:
            raise ValueError("At least two independent facilities with linked observations are required")
        provenance = matched_provenance(provenance, rows)
        model_features(rows, True)
        feature_manifest = {"baseline": FEATURES, "extended": FEATURES + OBSERVATION_NUMERIC,
                            "numeric_observation_features": OBSERVATION_NUMERIC,
                            "excluded_from_features": [*IDENTITY, LABEL, "reported_revenue_krw", "as_of", "cycle_end", "raw_json"],
                            "cutoff_days": cutoff_days, "window_days": window_days,
                            "as_of_definition": "cycle start + cutoff_days at 00:00 local naive source time",
                            "missing_values": "train-fold-only median and missing indicators; all-missing columns retained",
                            "prediction_scope": SCOPE, "target": "shipment", "unit": "kg", "crop": crop}
        cohort = rows[IDENTITY + ["as_of"]].to_dict("records")
        oof, comparison = compare_models(rows)
        selected = comparison["selected_methods"]["extended"]
        baseline_mae = comparison["models"]["baseline"][comparison["selected_methods"]["baseline"]]["mae"]
        extended_mae = comparison["models"]["extended"][selected]["mae"]
        comparison["observation_comparison"] = {
            "same_matched_cohort": True, "baseline_best_oof_mae_kg": baseline_mae,
            "extended_best_oof_mae_kg": extended_mae, "oof_mae_reduction_kg": baseline_mae - extended_mae,
            "interpretation": "Descriptive OOF comparison after model selection; not proof of real or causal improvement"}
        model = TrainFoldModel(selected, True).fit(rows, rows[LABEL])
        bundle = {**provenance, "features": FEATURES + OBSERVATION_NUMERIC,
                  "feature_manifest": feature_manifest, "feature_manifest_sha256": evidence_digest(feature_manifest),
                  "matched_cohort": cohort, "matched_cohort_sha256": evidence_digest({"rows": cohort}),
                  "selected_cpu_model": selected, "model": model, "model_fallback": model.fallback,
                  "training_crops": [crop], "target": "shipment", "unit": "kg", "prediction_scope": SCOPE,
                  "cutoff_days": cutoff_days, "window_days": window_days, "source_sha256": source_hashes(),
                  "raw_sources": sources, "limitations": LIMITATIONS}
        artifact = output_dir / "dsz_inseason_shipment.joblib"
        oof_path = output_dir / "dsz_inseason_oof.csv"
        features_path = output_dir / "dsz_inseason_training_rows.csv"
        joblib.dump(bundle, artifact)
        oof.to_csv(oof_path, index=False, encoding="utf-8-sig")
        rows[IDENTITY + ["as_of"] + FEATURES + OBSERVATION_NUMERIC + [LABEL]].to_csv(features_path, index=False, encoding="utf-8-sig")
        result = {key: value for key, value in bundle.items() if key != "model"}
        result.update(status="completed", **comparison, latest_year_check=latest_year_check(rows),
                      rows=len(rows), facilities=int(rows.facility_id.nunique()),
                      artifact_file=artifact.name, artifact_sha256=sha256(artifact),
                      oof_file=oof_path.name, oof_sha256=sha256(oof_path),
                      training_features_file=features_path.name, training_features_sha256=sha256(features_path),
                      observation_audit_file="observation_audit.json")
        write_json(metrics_path, result)
        return result
    except Exception as error:
        write_json(metrics_path, {"status": "failed", "data_kind": "unverified_input", "prediction_scope": SCOPE,
                                 "failure": {"type": type(error).__name__, "message": str(error)}})
        raise


def load_local_bundle(artifact_dir: Path) -> tuple[dict, dict]:
    """Load only self-generated trusted local joblib files, never untrusted uploads."""
    manifest = json.loads((artifact_dir / "dsz_inseason_metrics.json").read_text(encoding="utf-8"))
    if manifest.get("status") != "completed" or manifest.get("prediction_scope") != SCOPE:
        raise ValueError("Completed in-season training artifacts are required")
    require_model_confirmation(manifest)
    if manifest.get("source_sha256") != source_hashes():
        raise ValueError("Current model/feature-builder source hashes differ from training")
    if manifest.get("features") != FEATURES + OBSERVATION_NUMERIC:
        raise ValueError("Artifact feature whitelist differs")
    if evidence_digest(manifest["feature_manifest"]) != manifest.get("feature_manifest_sha256"):
        raise ValueError("Feature manifest SHA differs")
    if evidence_digest({"rows": manifest["matched_cohort"]}) != manifest.get("matched_cohort_sha256"):
        raise ValueError("Matched cohort SHA differs")
    path = artifact_dir / manifest["artifact_file"]
    if path.resolve().parent != artifact_dir.resolve() or sha256(path) != manifest["artifact_sha256"]:
        raise ValueError("Local model artifact path/SHA differs")
    bundle = joblib.load(path)
    for key, value in bundle.items():
        if key != "model" and value != manifest.get(key):
            raise ValueError(f"Model/manifest provenance mismatch: {key}")
    require_model_confirmation(bundle)
    return bundle, manifest


def predict_inseason(artifact_dir: Path, input_dir: Path, requests: pd.DataFrame, *, encoding: str = "utf-8-sig") -> tuple[pd.DataFrame, dict]:
    if set(requests.columns) != {"plan_id", "facility_id", "cycle_id"} or requests.empty:
        raise ValueError("Requests must contain only plan_id, facility_id, cycle_id and at least one row")
    if requests.isna().any().any():
        raise ValueError("Request identities cannot be missing")
    requests = requests.astype(str).copy()
    if requests.apply(lambda column: column.str.strip().eq("")).any().any() or requests.plan_id.duplicated().any() or requests.duplicated(["facility_id", "cycle_id"]).any():
        raise ValueError("Request identities must be present and unique")
    bundle, manifest = load_local_bundle(artifact_dir)
    tables, sources, validation = load_observation_tables(input_dir, encoding=encoding)
    request_rows = requests.rename(columns={"plan_id": "row_id"})
    rows, audit = build_observation_features(tables, request_rows, bundle["cutoff_days"], bundle["window_days"])
    expected = set(map(tuple, request_rows[IDENTITY].to_numpy()))
    actual = set(map(tuple, rows[IDENTITY].to_numpy()))
    absent = rows.loc[~rows.has_observations, IDENTITY].to_dict("records")
    if expected != actual or absent:
        raise ValueError("Unmatched/invalid request or no observations; no silent baseline fallback: "
                         + json.dumps({"excluded_requests": audit.get("excluded_requests", []), "no_observations": absent}, ensure_ascii=False))
    if not set(rows.crop).issubset(bundle["training_crops"]):
        raise ValueError("Query crop is outside the trained crop scope")
    today = pd.Timestamp(datetime.now().date())
    if pd.to_datetime(rows.as_of).gt(today).any():
        raise ValueError("A requested prediction cutoff is in the future; observed inputs are not yet available")
    synthetic = rows.facility_id.str.startswith("SYN_FARM_")
    if (bundle["data_kind"] == "synthetic_schema_fixture" and not synthetic.all()) or (
            bundle["data_kind"] != "synthetic_schema_fixture" and synthetic.any()):
        raise ValueError("Synthetic and real facility identities cannot be mixed")
    result = rows[IDENTITY + ["as_of"]].rename(columns={"row_id": "plan_id"}).copy()
    result["prediction"] = bundle["model"].predict(rows)
    for name in ["target", "unit", "prediction_scope", "cutoff_days", "window_days", "data_kind", "target_assumption",
                 "target_period_confirmed", "target_period_evidence_sha256", "source_manifest_sha256", "candidate_sha256",
                 "training_cohort_sha256", "matched_cohort_sha256", "feature_manifest_sha256", "selected_cpu_model"]:
        result[name] = bundle[name]
    result["query_sources_sha256"] = evidence_digest({"sources": sources})
    result["training_artifact_sha256"] = manifest["artifact_sha256"]
    result["interpretation"] = "SYNTHETIC RUNTIME DEMO ONLY" if bundle["data_kind"] == "synthetic_schema_fixture" else "Whole-cycle shipment update; retrospective availability assumptions, not economic or causal validation"
    metadata = {"prediction_scope": SCOPE, "data_kind": bundle["data_kind"], "raw_sources": sources,
                "query_sources_sha256": evidence_digest({"sources": sources}), "observation_audit": audit,
                "validation_issues": validation, "source_sha256": bundle["source_sha256"],
                "training_manifest_sha256": sha256(artifact_dir / "dsz_inseason_metrics.json"),
                "training_artifact_sha256": manifest["artifact_sha256"], "feature_manifest": bundle["feature_manifest"],
                "limitations": LIMITATIONS}
    return result, metadata
