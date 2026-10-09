"""Train offline DSZ schema candidates; synthetic scores prove execution only."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

for variable in ["OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"]:
    os.environ[variable] = "2"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import joblib  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from src.dsz_model import CATEGORICAL, FEATURES, NUMERIC, TARGETS, features, fit_target, grouped_folds, prepare_target, scores, sha256  # noqa: E402


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_data(data_dir):
    manifest_path = data_dir / "dsz_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    candidate = manifest["artifacts"]["candidates"]
    path = data_dir / candidate["file"]
    if path.resolve().parent != data_dir.resolve() or sha256(path) != candidate["sha256"]:
        raise ValueError("Candidate path or SHA differs from preparation manifest")
    if manifest["features"] != FEATURES:
        raise ValueError("Preparation/model feature contracts differ")
    string_columns = CATEGORICAL + ["row_id", "facility_id", "cycle_id", "data_kind", "target_assumption"]
    numeric_columns = NUMERIC + [value[0] for value in TARGETS.values()]
    rows = pd.read_csv(path, encoding="utf-8-sig", dtype={name: str for name in string_columns},
                       keep_default_na=False, na_values={name: [""] for name in numeric_columns})
    data_kind = manifest["data_kind"]
    if data_kind not in {"synthetic_schema_fixture", "onsite_private_unverified"}:
        raise ValueError("Unknown data_kind")
    for name in ["data_kind", "target_assumption"]:
        if not rows[name].eq(manifest[name]).all():
            raise ValueError(f"Candidate/manifest provenance mismatch: {name}")
    synthetic_ids = rows["facility_id"].astype(str).str.startswith("SYN_FARM_")
    if len(rows) and ((data_kind == "synthetic_schema_fixture" and not synthetic_ids.all())
                      or (data_kind != "synthetic_schema_fixture" and synthetic_ids.any())):
        raise ValueError("Synthetic facility identity and provenance disagree")
    provenance = {"data_kind": data_kind, "target_assumption": manifest["target_assumption"],
                  "target_period_confirmed": manifest["target_period_confirmed"],
                  "source_manifest_sha256": sha256(manifest_path), "candidate_sha256": sha256(path),
                  "source_schema_sha256": manifest["schema_sha256"],
                  "interpretation": "SYNTHETIC RUNTIME DEMO ONLY" if data_kind == "synthetic_schema_fixture"
                  else "Unverified recorded candidates; assumptions require onsite confirmation"}
    return rows, provenance, manifest


def regression_check(predictor, train_x, train_y, query_x):
    import torch
    altered = query_x.copy()
    for i, name in enumerate(FEATURES):
        altered[:, i] = 1_000_000 if name in NUMERIC else "__unseen_query__"
    snapshots = []
    for query in [query_x, altered]:
        inputs, standardized_y = predictor._prepare_reg_context(train_x, train_y, query)
        contexts = []
        for i, (values, categories) in enumerate(inputs):
            transformed, transformed_y, _ = predictor.get_xy_reg(
                values.copy(), i, standardized_y.copy(), predictor.preprocess_pipelines[i],
                categories.copy(), "Regression", unique_dataset_name="dsz_path_check")
            width = predictor.model.features_per_group
            padded = np.pad(transformed, ((0, 0), (0, (-transformed.shape[1]) % width)))
            tensor = torch.as_tensor(padded, dtype=torch.float32).reshape(1, len(padded), -1, width)
            with torch.inference_mode():
                internal = predictor.model.x_preprocess({"data": tensor, "eval_pos": len(train_x)})
            contexts.append((transformed[:len(train_x)].copy(), transformed_y.copy(),
                             internal["data"][:, :len(train_x)].numpy().copy()))
        snapshots.append(contexts)
    for normal, changed in zip(*snapshots, strict=True):
        np.testing.assert_allclose(normal[0], changed[0], atol=1e-12, rtol=1e-12, equal_nan=True)
        np.testing.assert_array_equal(normal[1], changed[1])
        np.testing.assert_allclose(normal[2], changed[2], atol=1e-6, rtol=1e-6, equal_nan=True)
    return {"pipelines_checked": len(snapshots[0]), "training_transforms_query_invariant": True,
            "internal_normalization_query_invariant": True, "heldout_labels_passed": False}


def run_limix_worker(data_dir, output_dir):
    # These optional modules/weights are deliberately absent from the CPU bundle.
    helper = ROOT / "scripts/train_adp_timing.py"
    if not helper.exists():
        raise RuntimeError("Optional pinned LimiX runtime is not included in the CPU bundle; omit --include-limix")
    from scripts.train_adp_timing import load_limix
    candidates, provenance, _ = read_data(data_dir)
    predictor, metadata = load_limix()  # Validates CUDA, pinned local weights/code; never downloads.
    result = {**provenance, "status": "running", "model": metadata, "targets": {}}
    for target, (label, _, unit) in TARGETS.items():
        rows = prepare_target(candidates, target)
        if rows["facility_id"].nunique() < 2:
            result["targets"][target] = {"status": "skipped_insufficient_data", "unit": unit,
                                         "reason": "Fewer than two facilities with eligible target records"}
            continue
        x = features(rows).to_numpy(object)
        predicted = np.full(len(rows), np.nan)
        checks, assignments = [], np.full(len(rows), -1)
        for number, (train, query) in enumerate(grouped_folds(rows)):
            print(f"LimiX {target} fold={number} data_kind={provenance['data_kind']}", flush=True)
            checks.append({"fold": number, **regression_check(predictor, x[train], rows.iloc[train][label].to_numpy(float), x[query])})
            predicted[query] = np.maximum(np.asarray(predictor.predict(
                x[train], rows.iloc[train][label].to_numpy(float), x[query], task_type="Regression",
                unique_dataset_name=f"dsz_{target}_{number}"), dtype=float).reshape(-1), 0)
            assignments[query] = number
        oof = rows[["row_id", "facility_id", "cycle_id", "data_kind", "target_assumption", label]].copy()
        oof["fold"], oof["limix_2_400m"] = assignments, predicted
        oof["source_manifest_sha256"] = provenance["source_manifest_sha256"]
        path = output_dir / f"dsz_{target}_limix_oof.csv"
        oof.to_csv(path, index=False, encoding="utf-8-sig")
        result["targets"][target] = {"status": "completed", "unit": unit, **scores(rows[label], predicted), "checks": checks,
            "by_fold": {str(fold): scores(group[label], group["limix_2_400m"]) for fold, group in oof.groupby("fold")},
            "oof_file": path.name, "oof_sha256": sha256(path)}
    result["status"] = "completed"
    result["selection"] = "Optional frozen LimiX comparison only; CPU deployment selection is unchanged"
    write_json(output_dir / "dsz_limix_comparison.json", result)


def train(data_dir, output_dir, include_limix=False, limix_python=None):
    started = time.perf_counter()
    output_dir.mkdir(parents=True, exist_ok=True)
    metrics_path = output_dir / "dsz_model_metrics.json"
    try:
        candidates, provenance, manifest = read_data(data_dir)
    except Exception as error:
        write_json(metrics_path, {"status": "failed", "data_kind": "unverified_input",
                                  "failure": {"type": type(error).__name__, "message": str(error)}})
        raise
    result = {**provenance, "status": "running", "created_at_utc": datetime.now(timezone.utc).isoformat(),
              "features": FEATURES, "target_units": manifest["target_units"], "targets": {},
              "source_sha256": {name: sha256(ROOT / name) for name in
                                ["src/dsz_model.py", "scripts/train_dsz.py", "scripts/predict_dsz.py"]},
              "limitations": ["Synthetic results are execution tests, never real farm accuracy.",
                              "Target assumption is explicit; recorded values are not certified full-cycle totals.",
                              "Same facility cycles stay together; future-year and causal performance are not established.",
                              "CPU model selection uses the same OOF data; no untouched final test.",
                              "Revenue is gross receipts, not profit. No annualization or investment payback is inferred."]}
    write_json(metrics_path, result)
    try:
        for target in TARGETS:
            print(f"Training {target}: {provenance['data_kind']}", flush=True)
            rows = prepare_target(candidates, target)
            facility_count = int(rows["facility_id"].nunique())
            if facility_count < 2:
                result["targets"][target] = {"status": "skipped_insufficient_data", "rows": len(rows),
                    "facilities": facility_count, "target_column": TARGETS[target][0], "unit": TARGETS[target][2],
                    "reason": "Fewer than two independent facilities with eligible target records"}
                write_json(metrics_path, result)
                continue
            bundle, oof, summary = fit_target(rows, target, provenance)
            bundle_path = output_dir / f"dsz_{target}.joblib"
            oof_path = output_dir / f"dsz_{target}_oof.csv"
            joblib.dump(bundle, bundle_path)
            oof.to_csv(oof_path, index=False, encoding="utf-8-sig")
            summary.update(artifact_file=bundle_path.name, artifact_sha256=sha256(bundle_path),
                           oof_file=oof_path.name, oof_sha256=sha256(oof_path))
            result["targets"][target] = summary
            write_json(metrics_path, result)
        if not any(record["status"] == "completed" for record in result["targets"].values()):
            raise ValueError("Neither target has enough eligible independent facilities")
        if include_limix:
            python = Path(limix_python) if limix_python else ROOT / ".venv-limix/Scripts/python.exe"
            if not python.is_file():
                raise RuntimeError("LimiX Python runtime unavailable; supply --limix-python or omit --include-limix")
            subprocess.run([str(python), "-X", "utf8", str(Path(__file__).resolve()),
                            "--data-dir", str(data_dir.resolve()), "--output-dir", str(output_dir.resolve()),
                            "--limix-worker"], check=True)
            path = output_dir / "dsz_limix_comparison.json"
            extra = json.loads(path.read_text(encoding="utf-8"))
            if extra["candidate_sha256"] != provenance["candidate_sha256"] or extra["data_kind"] != provenance["data_kind"]:
                raise ValueError("Optional LimiX results use different data")
            result["optional_limix"] = {"file": path.name, "sha256": sha256(path), "status": extra["status"]}
        result["status"] = "completed"
        result["seconds"] = time.perf_counter() - started
        write_json(metrics_path, result)
        lines = ["# DSZ offline model execution", "", f"**{provenance['interpretation']}**", "",
                 f"data_kind: {provenance['data_kind']}", f"target_assumption: {provenance['target_assumption']}", "",
                 "OOF scores select a CPU model; they are not an independent final test.", "",
                 "| Target | Unit | Rows | Method | MAE | RMSE |", "|---|---|---:|---|---:|---:|"]
        for target, record in result["targets"].items():
            if record["status"] != "completed":
                lines.append(f"| {target} | {record['unit']} | {record['rows']} | skipped_insufficient_data | — | — |")
            for name, score in record.get("models", {}).items():
                lines.append(f"| {target} | {record['unit']} | {record['rows']} | {name} | {score['mae']:.4f} | {score['rmse']:.4f} |")
            if record.get("constant_training_fallbacks"):
                lines.append("\nAudited constant-training median fallbacks: " + json.dumps(record["constant_training_fallbacks"]))
        lines += ["", *result["limitations"]]
        (output_dir / "dsz_training_report.md").write_text("\n".join(lines), encoding="utf-8")
        return result
    except Exception as error:
        result.update(status="failed", failure={"type": type(error).__name__, "message": str(error)})
        write_json(metrics_path, result)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--include-limix", action="store_true", help="Opt into local approved CUDA comparison; no downloads")
    parser.add_argument("--limix-python", type=Path)
    parser.add_argument("--limix-worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.limix_worker:
        run_limix_worker(args.data_dir, args.output_dir)
    else:
        summary = train(args.data_dir, args.output_dir, args.include_limix, args.limix_python)
        print(json.dumps({"status": summary["status"], "data_kind": summary["data_kind"],
                          "output_dir": str(args.output_dir.resolve())}, ensure_ascii=False))
