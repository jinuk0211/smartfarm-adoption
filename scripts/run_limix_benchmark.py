"""Run the 400M LimiX-2 checkpoint on the existing chronological RDA holdouts.

Built with StableAI LimiX. This is a local, non-commercial benchmark only.
No held-out target is passed to the predictor, and no equipment effect is fitted.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gc
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "data/raw/limix_model"
VENDOR = ROOT / "vendor/limix"
REVISION = "de07b679e74a41b50b9de18251a8fa245e537440"
CODE_REVISION = "516bf396333feb3198cf7aff8a6c10421f218e24"
CHECKPOINT_SHA = "ed01f7a0a18d25451bc9d1058b479ba6b68048aa1ebde06156c8fcfaf8b8fe81"
CHECKPOINT_BYTES = 1625774719
FEATURES = ["year", "crop", "cultivation_type", "region"]
TARGET = "yield_kg_per_1000m2"
KEYS = FEATURES + ["period_basis", "source_category"]


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def fetch_model() -> None:
    """Download the pinned official checkpoint without a duplicate HF disk cache."""
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {"repo": "stable-ai/LimiX-2", "revision": REVISION, "files": []}
    for filename in ["LICENSE", "README.md", "config.json", "LimiX-2.ckpt"]:
        destination = MODEL_DIR / filename
        url = f"https://huggingface.co/stable-ai/LimiX-2/resolve/{REVISION}/{filename}"
        if not destination.exists():
            expected = CHECKPOINT_BYTES if filename.endswith(".ckpt") else 1_000_000
            if shutil.disk_usage(MODEL_DIR).free < expected + 3_000_000_000:
                raise RuntimeError("Download would leave less than 3 GB free system-disk space")
            temporary = destination.with_suffix(destination.suffix + ".partial")
            digest = hashlib.sha256()
            downloaded = 0
            last_report = time.monotonic()
            with urllib.request.urlopen(url, timeout=60) as response, temporary.open("wb") as output:
                while block := response.read(4 * 1024 * 1024):
                    output.write(block)
                    digest.update(block)
                    downloaded += len(block)
                    if time.monotonic() - last_report >= 20:
                        print(f"Downloading {filename}: {downloaded / 1e6:.0f} MB", flush=True)
                        last_report = time.monotonic()
            if filename.endswith(".ckpt") and digest.hexdigest() != CHECKPOINT_SHA:
                raise RuntimeError("Downloaded checkpoint SHA256 differs from official LFS object")
            temporary.replace(destination)
        checksum = sha256(destination)
        if filename.endswith(".ckpt") and checksum != CHECKPOINT_SHA:
            raise RuntimeError("Existing checkpoint SHA256 differs from official LFS object")
        manifest["files"].append({"file": filename, "url": url, "bytes": destination.stat().st_size,
                                  "sha256": checksum})
        print(f"Verified {filename}: {destination.stat().st_size} bytes", flush=True)
    manifest["retrieved_at_utc"] = datetime.now(timezone.utc).isoformat()
    write_json(MODEL_DIR / "source_manifest.json", manifest)


def prepare_splits():
    """Match original rows, support flags, counts and targets before any inference."""
    import numpy as np
    import pandas as pd

    raw = pd.read_csv(ROOT / "data/processed/rda_crop_income.csv", encoding="utf-8-sig")
    audit = json.loads((ROOT / "artifacts/data_audit.json").read_text(encoding="utf-8"))
    if sha256(ROOT / "data/processed/rda_crop_income.csv") not in audit["input_sha256"].values():
        raise ValueError("RDA source differs from the original model benchmark input")
    raw["source_category"] = raw["crop_original"]
    raw["geographic_scope"] = np.where(raw["region"].eq("전국"), "national", "regional")
    original = pd.read_csv(ROOT / "artifacts/holdout_predictions.csv", encoding="utf-8-sig")
    metrics = json.loads((ROOT / "artifacts/model_metrics.json").read_text(encoding="utf-8"))
    splits = []
    for group in metrics["groups"]:
        selected = raw.loc[
            raw["geographic_scope"].eq(group["geographic_scope"])
            & raw["schema_regime"].eq(group["classification_regime"])
            & raw["period_basis"].eq(group["period_basis"])
        ].copy()
        train = selected.loc[selected.year < group["holdout_year"]].copy()
        heldout = original.loc[original.group_id.eq(group["group_id"])].copy()
        check = heldout.merge(selected[KEYS + [TARGET]], on=KEYS, suffixes=("", "_raw"),
                              how="left", validate="one_to_one")
        if not (check[TARGET] == check[TARGET + "_raw"]).all():
            raise ValueError("Holdout targets or identities differ from the current raw source")
        if len(selected) != group["n_rows"] or len(train) != group["n_train"] or len(heldout) != group["n_test"]:
            raise ValueError("Training/holdout size mismatch with original benchmark")
        if train.year.max() >= heldout.year.min():
            raise ValueError("A training year is not strictly earlier than the holdout")
        support_keys = KEYS[1:]
        supported = heldout[support_keys].apply(tuple, axis=1).isin(
            set(train[support_keys].apply(tuple, axis=1)))
        if not np.array_equal(supported.to_numpy(), heldout.supported_by_training.to_numpy(dtype=bool)):
            raise ValueError("Support flags differ from the original benchmark")
        if int(supported.sum()) != group["metrics"]["historical_median"]["n_scored"]:
            raise ValueError("Scored-row count differs from the original benchmark")
        splits.append((group, train, heldout, supported.to_numpy()))
    return splits


def use_torch_norm(config: dict) -> None:
    """Use the upstream PyTorch RMSNorm implementation on Windows without Triton."""
    for key, value in config.items():
        if key == "rmsnorm_impl":
            config[key] = "torch"
        elif isinstance(value, dict):
            use_torch_norm(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    use_torch_norm(item)


def check_preprocessing() -> dict:
    """Check numeric distribution fitting and the selected norm implementation."""
    import numpy as np
    import torch
    from inference.v2_0.preprocess import RebalanceFeatureDistribution
    from model.v2_0.operators.rmsnorm import build_rmsnorm
    context = np.arange(12, dtype=float).reshape(-1, 1)
    outputs = []
    for query_value in [3.0, 1e12]:
        transform = RebalanceFeatureDistribution(
            worker_tags=["quantile_uniform_all_data"], original_flag=True,
            discrete_flag=False, svd_tag=None, enable_parallel=False, num_jobs=1)
        transformed, _ = transform.fit_transform(
            np.vstack([context, [[query_value]]]), [], 42, y=np.arange(len(context)))
        outputs.append(transformed[:len(context)])
    np.testing.assert_allclose(outputs[0], outputs[1], rtol=0, atol=0)
    norm = build_rmsnorm(4, eps=1e-5, elementwise_affine=False, norm_impl="torch")
    values = torch.tensor([[1.0, 2.0, 3.0, 4.0]])
    expected = values * torch.rsqrt(values.square().mean(dim=-1, keepdim=True) + 1e-5)
    torch.testing.assert_close(norm(values), expected)
    return {"query_extreme_does_not_change_train_quantiles": True,
            "torch_rmsnorm_matches_formula": True, "fixtures_used_for_training": False}


def check_actual_regression_path(predictor, splits) -> dict:
    """Change query covariates and check every actual regression training transform.

    This calls the same V2 _prepare_reg_context/get_xy_reg used by predict(),
    with real training rows and no query target supplied to either method.
    """
    import numpy as np
    import torch

    checked = []
    for group, train, heldout, _ in splits:
        x_train = train[FEATURES].to_numpy(dtype=object)
        y_train = train[TARGET].to_numpy(dtype=np.float64)
        normal_query = heldout[FEATURES].to_numpy(dtype=object)
        altered_query = normal_query.copy()
        altered_query[:, 0] = 100_000
        altered_query[:, 1:] = "unseen_query_category_only"
        snapshots = []
        for query in [normal_query, altered_query]:
            member_inputs, standardized_y = predictor._prepare_reg_context(x_train, y_train, query)
            transformed_contexts = []
            for index, (values, categories) in enumerate(member_inputs):
                transformed, transformed_y, _ = predictor.get_xy_reg(
                    values.copy(), index, standardized_y.copy(), predictor.preprocess_pipelines[index],
                    categories.copy(), "Regression", unique_dataset_name="strict_path_validation")
                group_width = predictor.model.features_per_group
                padding = (-transformed.shape[1]) % group_width
                padded = np.pad(transformed, ((0, 0), (0, padding)))
                tensor = torch.as_tensor(padded, dtype=torch.float32).reshape(
                    1, len(padded), -1, group_width)
                with torch.inference_mode():
                    internal = predictor.model.x_preprocess({"data": tensor, "eval_pos": len(train)})
                internal_train = internal["data"][:, :len(train)].numpy().copy()
                transformed_contexts.append((transformed[:len(train)].copy(), transformed_y.copy(),
                                             internal_train))
            snapshots.append(transformed_contexts)
        for normal, altered in zip(*snapshots, strict=True):
            np.testing.assert_allclose(normal[0], altered[0], rtol=1e-12, atol=1e-12, equal_nan=True)
            np.testing.assert_array_equal(normal[1], altered[1])
            np.testing.assert_allclose(normal[2], altered[2], rtol=1e-6, atol=1e-6, equal_nan=True)
        checked.append({"group_id": group["group_id"], "pipelines_checked": len(snapshots[0]),
                        "training_transforms_unchanged_when_queries_change": True,
                        "internal_model_preprocessing_train_values_unchanged": True})
    return {"actual_regression_path": True, "groups": checked, "query_targets_passed": False}


def run_benchmark(groups: list[str] | None) -> None:
    for variable in ["OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"]:
        os.environ[variable] = "2"
    os.environ["LIMIX_REUSE_FROZEN_MODEL"] = "0"
    os.environ["LIMIX_CACHE_DIR"] = str(MODEL_DIR / "preprocess_cache")
    import numpy as np
    import pandas as pd
    import torch

    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    splits = prepare_splits()
    checkpoint_path = MODEL_DIR / "LimiX-2.ckpt"
    if sha256(checkpoint_path) != CHECKPOINT_SHA:
        raise ValueError("Official checkpoint checksum validation failed")
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=VENDOR, text=True).strip()
    if revision != CODE_REVISION:
        raise ValueError("Vendor code revision changed")
    actual_patch = subprocess.check_output(["git", "diff", "HEAD", "--no-ext-diff"], cwd=VENDOR)
    patch_sha = hashlib.sha256(actual_patch).hexdigest()
    if patch_sha != sha256(ROOT / "artifacts/limix_windows_compatibility.patch"):
        raise ValueError("Actual vendor changes differ from the reviewed compatibility patch")
    untracked = subprocess.check_output(
        ["git", "ls-files", "--others", "--exclude-standard"], cwd=VENDOR, text=True).splitlines()
    if any(Path(path).suffix in {".py", ".pyd"} for path in untracked):
        raise ValueError("Unexpected untracked Python code in vendor directory")
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA unavailable; this experiment does not silently switch hardware or model")
    torch.cuda.set_per_process_memory_fraction(0.75)
    sys.path.insert(0, str(VENDOR))
    from inference.predictor import LimiXPredictor

    preprocessing_checks = check_preprocessing()
    write_json(ROOT / "artifacts/limix_preprocessing_checks.json", preprocessing_checks)
    # mmap avoids duplicating 1.63 GB of checkpoint weights in physical RAM.
    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=True, mmap=True)
    if not checkpoint["config"]["preprocess_config_x"]["normalize_on_train_only"]:
        raise ValueError("Checkpoint internal normalization must use training context only")
    original_norm = checkpoint["config"].get("rmsnorm_impl", "triton")
    use_torch_norm(checkpoint["config"])
    checkpoint["config"]["rmsnorm_impl"] = "torch"
    inference_config = json.loads((VENDOR / "config/reg_default_noretrieval_v2.json").read_text())
    results = {"model": "LimiX-2 (400M)", "code_revision": CODE_REVISION,
               "variant": "strict_train_only_regression",
               "checkpoint_revision": REVISION, "checkpoint_sha256": CHECKPOINT_SHA,
               "source_csv_sha256": sha256(ROOT / "data/processed/rda_crop_income.csv"),
               "original_metrics_sha256": sha256(ROOT / "artifacts/model_metrics.json"),
               "vendor_patch_sha256": patch_sha,
               "modified_vendor_files_sha256": {
                   name: sha256(VENDOR / name) for name in subprocess.check_output(
                       ["git", "diff", "HEAD", "--name-only"], cwd=VENDOR, text=True).splitlines()},
               "status": "running", "requested_groups": groups or [entry[0]["group_id"] for entry in splits],
               "preprocessing_checks": preprocessing_checks,
               "features": FEATURES, "target": TARGET, "seed": 42,
               "hardware": torch.cuda.get_device_name(0), "torch_version": torch.__version__,
               "original_norm": original_norm, "runtime_norm": "torch",
               "model_construction_device": "cuda:0", "checkpoint_memory_mapped": True,
               "checkpoint_preprocess_config": checkpoint["config"]["preprocess_config_x"],
               "inference_config": inference_config, "query_batch_size": 8,
               "validation": "Same source rows, chronological groups and support mask as model_metrics.json",
               "limitation": "RDA crop-region aggregates, not individual farms or causal adoption effects",
               "started_at_utc": datetime.now(timezone.utc).isoformat(), "groups": []}
    write_json(ROOT / "artifacts/limix_metrics.json", results)
    print("Loading LimiX-2 400M checkpoint", flush=True)
    # Construct weights directly on the GPU instead of allocating a second full
    # copy on an 8 GB RAM desktop. The pretrained tensors are unchanged.
    with torch.device("cuda:0"):
        predictor = LimiXPredictor(device=torch.device("cuda:0"), model_path=str(checkpoint_path),
                                  inference_config=inference_config, ckpt=checkpoint,
                                  test_batch_mode="fixed", test_batch_size=8,
                                  enable_preprocess_parallel=False, preprocess_num_jobs=1,
                                  mix_precision=True, use_data_cache=False, seed=42)
    del checkpoint
    gc.collect()
    results["actual_parameter_count"] = sum(p.numel() for p in predictor.model.parameters())
    print("Checking actual regression transforms against changed query features", flush=True)
    results["regression_path_checks"] = check_actual_regression_path(predictor, splits)
    results["preprocessing_protocol"] = "train_only_regression_v2"
    write_json(ROOT / "artifacts/limix_regression_path_checks.json", results["regression_path_checks"])
    write_json(ROOT / "artifacts/limix_metrics.json", results)
    predictions = []
    for group, train, heldout, support in splits:
        if groups and group["group_id"] not in groups:
            continue
        start = time.perf_counter()
        torch.cuda.reset_peak_memory_stats()
        print(f"Predicting {group['group_id']}: context={len(train)}, query={len(heldout)}", flush=True)
        # Explicitly separate query features from the holdout labels.
        predicted = predictor.predict(train[FEATURES].to_numpy(dtype=object),
                                      train[TARGET].to_numpy(dtype=np.float64),
                                      heldout[FEATURES].to_numpy(dtype=object),
                                      task_type="Regression", unique_dataset_name=group["group_id"])
        predicted = np.asarray(predicted, dtype=np.float64).reshape(-1)
        if predicted.shape != (len(heldout),) or not np.isfinite(predicted).all():
            raise ValueError("LimiX did not return finite predictions for all query rows")
        clipped = np.maximum(predicted, 0)
        errors = clipped[support] - heldout[TARGET].to_numpy()[support]
        result = {"group_id": group["group_id"], "n_train": len(train), "n_test": len(heldout),
                  "n_scored": int(support.sum()), "train_years": group["train_years"],
                  "holdout_year": group["holdout_year"], "mae_kg_per_1000m2": float(np.mean(abs(errors))),
                  "rmse_kg_per_1000m2": float(np.sqrt(np.mean(errors ** 2))),
                  "seconds": time.perf_counter() - start,
                  "peak_gpu_allocated_bytes": torch.cuda.max_memory_allocated(),
                  "baseline_mae": group["metrics"]["historical_median"]["mae_kg_per_1000m2"],
                  "negative_predictions_clipped": int((predicted < 0).sum())}
        results["groups"].append(result)
        scored = heldout.copy()
        scored["limix_raw_prediction"] = predicted
        scored["limix_prediction"] = np.where(support, clipped, np.nan)
        predictions.append(scored)
        pd.concat(predictions, ignore_index=True).to_csv(ROOT / "artifacts/limix_holdout_predictions.csv",
                                                       index=False, encoding="utf-8-sig")
        write_json(ROOT / "artifacts/limix_metrics.json", results)
        print(json.dumps(result, ensure_ascii=False), flush=True)
    results["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
    results["status"] = "completed"
    write_json(ROOT / "artifacts/limix_metrics.json", results)
    # Upstream close() moves the full model back to CPU. This one-shot benchmark
    # is finished, so release GPU weights directly without that RAM allocation.
    predictor.model = None
    gc.collect()
    torch.cuda.empty_cache()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", action="store_true", help="Download and verify pinned official model")
    parser.add_argument("--check-splits", action="store_true", help="Verify existing benchmark identities only")
    parser.add_argument("--groups", nargs="+", choices=["rda_0", "rda_1", "rda_2", "rda_3"])
    args = parser.parse_args()
    print(f"PID={os.getpid()}", flush=True)
    if args.fetch:
        fetch_model()
    elif args.check_splits:
        for group, train, heldout, support in prepare_splits():
            print(f"{group['group_id']}: train={len(train)}, holdout={len(heldout)}, scored={support.sum()}")
    else:
        write_json(ROOT / "artifacts/limix_metrics.json", {
            "status": "running", "started_at_utc": datetime.now(timezone.utc).isoformat(),
            "model": "LimiX-2 (400M)", "groups": [],
        })
        run_benchmark(args.groups)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        failure = {
            "time_utc": datetime.now(timezone.utc).isoformat(),
            "error_type": type(error).__name__, "message": str(error),
            "traceback": traceback.format_exc(),
        }
        write_json(ROOT / "artifacts/limix_last_failure.json", failure)
        if "--fetch" not in sys.argv and "--check-splits" not in sys.argv:
            metrics_path = ROOT / "artifacts/limix_metrics.json"
            result = json.loads(metrics_path.read_text(encoding="utf-8")) if metrics_path.exists() else {}
            result.update(status="failed", failure=failure)
            write_json(metrics_path, result)
        raise
