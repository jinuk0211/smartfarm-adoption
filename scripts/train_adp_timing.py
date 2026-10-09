"""Run classical then LimiX stages in their existing isolated environments."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gc
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback

for variable in ["OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"]:
    os.environ[variable] = "2"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402 -- bound native threads before importing numerical libraries
import pandas as pd  # noqa: E402

from scripts import run_limix_benchmark as engine  # noqa: E402
from src.adp_timing_model import (FEATURES, TARGET, SEED, classical_predictions, features,  # noqa: E402
                                 grouped_folds, prepare_rows, summarize_predictions)

METRICS = ROOT / "artifacts/adp_timing_metrics.json"
OOF = ROOT / "artifacts/adp_timing_oof_predictions.csv"
CLASSICAL = ["crop_median", "crop_month_median", "catboost", "xgboost"]
LIMITATIONS = [
    "Target is days from planting to first shipment recorded in this file, not actual first harvest.",
    "Observation start, missing records and cycle completeness are unknown; no economic target is inferred.",
    "Farm group hashes use province/city/local farm code; stable physical farm identity is unverified.",
    "Five-fold comparison reuses all observed eligible rows; there is no untouched final evaluation set.",
    "Cycles without shipment records are unobserved and excluded, not zero-day or failed-farm labels.",
    "Grouping prevents observed local code overlap, not unseen aliases of the same physical farm.",
    "Results do not validate generalization to new years or service deployment for new farms.",
]


def read_inputs():
    paths = [ROOT / "data/processed/adp_cultivation_cycles.csv", ROOT / "data/processed/adp_cycle_quality.csv"]
    rows, audit = prepare_rows(*(pd.read_csv(path, encoding="utf-8-sig") for path in paths))
    hashes = {path.name: engine.sha256(path) for path in paths}
    folds = grouped_folds(rows)
    fold_records = [{"fold": number, "n_train": len(train), "n_test": len(test),
                     "n_train_groups": int(rows.iloc[train]["farm_group_id"].nunique()),
                     "n_test_groups": int(rows.iloc[test]["farm_group_id"].nunique()),
                     "train_cycle_ids": rows.iloc[train]["cycle_id"].tolist(),
                     "test_cycle_ids": rows.iloc[test]["cycle_id"].tolist(),
                     "group_overlap": False} for number, (train, test) in enumerate(folds)]
    return rows, audit, hashes, folds, fold_records


def check_regression_path(predictor, train, query) -> dict:
    """Test the actual V2 path and internal normalization against changed queries."""
    import torch

    x_train, x_query = features(train).to_numpy(object), features(query).to_numpy(object)
    changed = x_query.copy()
    changed[:, :2] = 100_000
    changed[:, 2:] = "__query_only_unseen__"
    snapshots = []
    for query_values in [x_query, changed]:
        inputs, standardized_y = predictor._prepare_reg_context(x_train, train[TARGET].to_numpy(float), query_values)
        contexts = []
        for index, (values, categories) in enumerate(inputs):
            transformed, transformed_y, _ = predictor.get_xy_reg(
                values.copy(), index, standardized_y.copy(), predictor.preprocess_pipelines[index],
                categories.copy(), "Regression", unique_dataset_name="adp_timing_path_check")
            width = predictor.model.features_per_group
            padded = np.pad(transformed, ((0, 0), (0, (-transformed.shape[1]) % width)))
            tensor = torch.as_tensor(padded, dtype=torch.float32).reshape(1, len(padded), -1, width)
            with torch.inference_mode():
                internal = predictor.model.x_preprocess({"data": tensor, "eval_pos": len(train)})
            contexts.append((transformed[:len(train)].copy(), transformed_y.copy(),
                             internal["data"][:, :len(train)].numpy().copy()))
        snapshots.append(contexts)
    for ordinary, altered in zip(*snapshots, strict=True):
        np.testing.assert_allclose(ordinary[0], altered[0], atol=1e-12, rtol=1e-12, equal_nan=True)
        np.testing.assert_array_equal(ordinary[1], altered[1])
        np.testing.assert_allclose(ordinary[2], altered[2], atol=1e-6, rtol=1e-6, equal_nan=True)
    return {"pipelines_checked": len(snapshots[0]), "training_transforms_query_invariant": True,
            "internal_normalization_query_invariant": True, "heldout_targets_passed": False}


def load_limix():
    """Reuse the pinned, reviewed 400M engine without another download."""
    os.environ["LIMIX_REUSE_FROZEN_MODEL"] = "0"
    os.environ["LIMIX_CACHE_DIR"] = str(engine.MODEL_DIR / "preprocess_cache")
    import torch

    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    checkpoint_path = engine.MODEL_DIR / "LimiX-2.ckpt"
    if engine.sha256(checkpoint_path) != engine.CHECKPOINT_SHA:
        raise ValueError("LimiX checkpoint SHA mismatch")
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=engine.VENDOR, text=True).strip()
    patch = subprocess.check_output(["git", "diff", "HEAD", "--no-ext-diff"], cwd=engine.VENDOR)
    patch_sha = hashlib.sha256(patch).hexdigest()
    if revision != engine.CODE_REVISION or patch_sha != engine.sha256(ROOT / "artifacts/limix_windows_compatibility.patch"):
        raise ValueError("Vendor revision/patch differs from the reviewed engine")
    untracked = subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard"],
                                        cwd=engine.VENDOR, text=True).splitlines()
    if any(Path(path).suffix in {".py", ".pyd"} for path in untracked):
        raise ValueError("Untracked executable Python vendor code")
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA unavailable; no silent model or hardware substitution")
    torch.cuda.set_per_process_memory_fraction(0.75)
    sys.path.insert(0, str(engine.VENDOR))
    from inference.predictor import LimiXPredictor

    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=True, mmap=True)
    if not checkpoint["config"]["preprocess_config_x"]["normalize_on_train_only"]:
        raise ValueError("Internal normalization is not train-only")
    engine.use_torch_norm(checkpoint["config"])
    checkpoint["config"]["rmsnorm_impl"] = "torch"
    config = json.loads((engine.VENDOR / "config/reg_default_noretrieval_v2.json").read_text())
    with torch.device("cuda:0"):
        predictor = LimiXPredictor(device=torch.device("cuda:0"), model_path=str(checkpoint_path),
                                  inference_config=config, ckpt=checkpoint, test_batch_mode="fixed",
                                  test_batch_size=8, enable_preprocess_parallel=False,
                                  preprocess_num_jobs=1, mix_precision=True, use_data_cache=False, seed=SEED)
    del checkpoint
    gc.collect()
    metadata = {"checkpoint_sha256": engine.CHECKPOINT_SHA, "checkpoint_revision": engine.REVISION,
                "code_revision": revision, "vendor_patch_sha256": patch_sha,
                "actual_parameter_count": sum(p.numel() for p in predictor.model.parameters()),
                "hardware": torch.cuda.get_device_name(0), "torch_version": torch.__version__,
                "query_batch_size": 8, "inference_config": config,
                "training": "frozen pretrained weights; in-context regression, no fine-tuning"}
    return predictor, metadata


def report(result: dict) -> None:
    lines = ["# ADP 첫 기록출하 시점 탐색 비교", "", "Built with StableAI LimiX.", "",
             "타깃은 **정식일에서 파일 내 첫 기록출하일까지의 일수**이다. 실제 첫 수확일·최초 매출일·경제성 예측이 아니다.", "",
             f"상태: {result['status']}. 원자료 {result['data_audit']['n_source_cycles']}작기 중 "
             f"{result['data_audit']['n_included']}작기, {result['data_audit']['n_farm_groups']}농가 코드 그룹을 사용했다.", "",
             "전체 면적, 식부면적, 재식밀도, 판매·생산량, 출하 기록 수, 자료 유무와 품질 플래그는 입력에서 제외했다. "
             "품목·도·시군·온실 소재/형태·품종·정식 연월만 입력한다. 품종과 계획 일정 등은 실제 도입 전에 알 수 있는 값을 사용해야 한다.", "",
             "다섯 품목을 합쳐 학습하는 pooled-crop 비교이며 품목별 독립 학습 모델이 아니다. "
             "분할은 farm_group_id 기준 GroupKFold 5개로 고정했다. 같은 행에서 모든 모델의 OOF 예측을 비교하며, "
             "그룹은 관측된 지역+농가코드 기준이다. 학습 폴드 밖의 범주·정답으로 변환/중앙값을 적합하지 않는다. "
             "하이퍼파라미터 탐색이나 별도의 최종 평가셋은 없으므로 이는 비교 실험이다.", "",
             "| 모델 | 평가 행 | MAE(일) | RMSE(일) |", "|---|---:|---:|---:|"]
    for name, metrics in result["models"].items():
        lines.append(f"| {name} | {metrics['n_scored']} | {metrics['mae_days']:.3f} | {metrics['rmse_days']:.3f} |")
    lines += ["", "## 품목별 범위", "", "| 품목 | 작기 | 그룹 | 관측 타깃 최소/중앙/최대(일) |", "|---|---:|---:|---|"]
    for crop in result["data_audit"]["by_crop"]:
        lines.append(f"| {crop['crop']} | {crop['n_rows']} | {crop['n_groups']} | "
                     f"{crop['target_min_days']:.0f}/{crop['target_median_days']:.0f}/{crop['target_max_days']:.0f} |")
    lines += ["", "## 품목별 MAE(일)", "", "| 품목 | " + " | ".join(result["models"]) + " |",
              "|---|" + "---:|" * len(result["models"])]
    for crop in result["data_audit"]["by_crop"]:
        lines.append("| " + crop["crop"] + " | " + " | ".join(
            f"{metrics['by_crop'][crop['crop']]['mae_days']:.3f}" for metrics in result["models"].values()) + " |")
    lines += ["", "## 제외 및 해석 제한", "", "제외 건수: " + json.dumps(result["data_audit"]["exclusion_counts"], ensure_ascii=False), "",
              "정식 전 출하가 하나라도 있는 작기는 전체 제외했다. 출하 기록 없는 작기는 0으로 대체하지 않았다. "
              "정식과 출하가 같은 날인 관측은 0일로 유지했고, 길게 관측된 간격을 성능을 위해 자르지 않았다.", "",
              "관측 시작일·자료 완결성·농가코드의 실물 농가 및 연도 간 안정성이 확인되지 않았다. "
              "따라서 기록 누락이나 조사 시작시점까지 학습할 수 있다. 새 농가의 실제 첫 수확일이나 투자회수기간 서비스로 배포하지 않는다.", "",
              "## 재현", "", "`.venv/Scripts/python.exe -X utf8 scripts/train_adp_timing.py --stage classical`", "",
              "`.venv-limix/Scripts/python.exe -X utf8 scripts/train_adp_timing.py --stage limix`", "",
              "입력/스크립트 SHA256, 정확한 폴드별 train/test cycle_id, 품목·폴드별 점수, 패키지 버전과 실행시간은 "
              "`artifacts/adp_timing_metrics.json`에, 개별 OOF 예측은 `artifacts/adp_timing_oof_predictions.csv`에 보존했다. "
              "LimiX는 기존 공식 400M 체크포인트 및 검토된 Windows/학습전용 전처리 패치를 재사용한다. "
              + ("실제 V2 회귀와 내부 정규화에서 검증 입력을 바꿔도 학습 변환이 같은지 각 폴드별로 확인했다."
                 if result.get("limix", {}).get("preprocessing_protocol") == "train_only_regression_v2"
                 else "LimiX 실행 및 실제 회귀 경로 검증은 아직 완료되지 않았다."), "",
              "[원자료](https://adp.rda.go.kr/portal/pub/data/dataDetail.do?dataId=4163&dataTypeCd=PBLCATE), "
              "[단위 조사](adp_units_research.md). 데이터와 모델 실행은 로컬에서 수행했다."]
    (ROOT / "reports/adp_timing_experiment.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(stage: str) -> None:
    started = time.perf_counter()
    source_hashes = {name: engine.sha256(ROOT / name) for name in
                     ["src/adp_timing_model.py", "scripts/train_adp_timing.py", "scripts/run_limix_benchmark.py"]}
    rows, audit, hashes, folds, fold_records = read_inputs()
    if stage == "classical":
        result = {"status": "running", "started_at_utc": datetime.now(timezone.utc).isoformat(),
                  "target": TARGET, "features": FEATURES, "seed": SEED, "input_sha256": hashes,
                  "data_audit": audit, "split": "GroupKFold(n_splits=5, shuffle=False)",
                  "folds": fold_records, "limitations": LIMITATIONS, "models": {}, "stages": {}}
        oof = rows[["cycle_id", "farm_group_id", "crop", "planting_date", "first_shipment_date", TARGET]].copy()
        oof["fold"] = -1
        for name in CLASSICAL:
            oof[name] = np.nan
        names = CLASSICAL
    else:
        result = json.loads(METRICS.read_text(encoding="utf-8"))
        if result["input_sha256"] != hashes or result["folds"] != fold_records or result["stages"].get("classical", {}).get("status") != "completed":
            raise ValueError("Run the classical stage first with these exact inputs/folds")
        if result["oof_sha256"] != engine.sha256(OOF):
            raise ValueError("OOF file differs from the completed classical-stage artifact")
        # Preserve the already completed classical run's original hashes when
        # reading an artifact made before stage-specific provenance was added.
        result["stages"]["classical"].setdefault("source_sha256", result["script_sha256"])
        oof = pd.read_csv(OOF, encoding="utf-8-sig")
        if oof["cycle_id"].tolist() != rows["cycle_id"].tolist() or not np.array_equal(oof[TARGET], rows[TARGET]):
            raise ValueError("OOF row identity or target changed")
        oof["limix_2_400m"] = np.nan
        result["models"].pop("limix_2_400m", None)
        names = CLASSICAL + ["limix_2_400m"]
    result["status"] = "running"
    result["stages"][stage] = {"status": "running", "folds_completed": 0, "source_sha256": source_hashes}
    engine.write_json(METRICS, result)
    oof.to_csv(OOF, index=False, encoding="utf-8-sig")
    predictor = None
    try:
        if stage == "limix":
            predictor, metadata = load_limix()
            result["limix"] = metadata
            result["limix"]["regression_path_checks"] = []
        timings = []
        for number, (train_idx, test_idx) in enumerate(folds):
            train, query = rows.iloc[train_idx], rows.iloc[test_idx]
            fold_start = time.perf_counter()
            print(f"{stage} fold={number} train={len(train)} test={len(query)}", flush=True)
            if predictor is None:
                predictions = classical_predictions(train, query)
            else:
                checked = check_regression_path(predictor, train, query)
                result["limix"]["regression_path_checks"].append({"fold": number, **checked})
                predicted = predictor.predict(features(train).to_numpy(object), train[TARGET].to_numpy(float),
                                              features(query).to_numpy(object), task_type="Regression",
                                              unique_dataset_name=f"adp_recorded_timing_fold_{number}")
                predictions = {"limix_2_400m": np.maximum(np.asarray(predicted, dtype=float).reshape(-1), 0)}
            for name, values in predictions.items():
                if len(values) != len(query) or not np.isfinite(values).all():
                    raise ValueError(f"Invalid predictions for {name}")
                oof.loc[test_idx, name] = values
            oof.loc[test_idx, "fold"] = number
            timings.append(time.perf_counter() - fold_start)
            result["stages"][stage]["folds_completed"] = number + 1
            engine.write_json(METRICS, result)
            oof.to_csv(OOF, index=False, encoding="utf-8-sig")
        result["models"] = summarize_predictions(oof, names)
        result["stages"][stage] = {"status": "completed", "folds_completed": 5,
                                   "source_sha256": source_hashes,
                                   "total_seconds": time.perf_counter() - started, "fold_seconds": timings,
                                   "packages": {name: importlib.metadata.version(name) for name in
                                                (["numpy", "pandas", "scikit-learn", "catboost", "xgboost"]
                                                 if stage == "classical" else ["numpy", "pandas", "scikit-learn", "torch"])}}
        if stage == "limix":
            result["limix"]["preprocessing_protocol"] = "train_only_regression_v2"
        result["status"] = "completed" if stage == "limix" else "awaiting_limix"
        result["script_sha256"] = source_hashes
        result["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
        result["oof_sha256"] = engine.sha256(OOF)
        engine.write_json(METRICS, result)
        report(result)
        print(json.dumps({name: {key: value for key, value in metrics.items() if key in ["mae_days", "rmse_days", "n_scored"]}
                          for name, metrics in result["models"].items()}, ensure_ascii=False), flush=True)
    except Exception as error:
        result["status"] = "failed"
        result["stages"][stage].update(status="failed", error_type=type(error).__name__,
                                       error=str(error), traceback=traceback.format_exc())
        engine.write_json(METRICS, result)
        raise
    finally:
        if predictor is not None:
            predictor.model = None
            gc.collect()
            import torch
            torch.cuda.empty_cache()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=["classical", "limix"], required=True)
    args = parser.parse_args()
    print(f"PID={os.getpid()}", flush=True)
    try:
        main(args.stage)
    except Exception as error:
        # Even an early input/provenance failure must invalidate older success.
        failed = json.loads(METRICS.read_text(encoding="utf-8")) if METRICS.exists() else {}
        failed.update(status="failed", last_failure={"stage": args.stage,
                      "time_utc": datetime.now(timezone.utc).isoformat(),
                      "error_type": type(error).__name__, "error": str(error)})
        engine.write_json(METRICS, failed)
        raise
