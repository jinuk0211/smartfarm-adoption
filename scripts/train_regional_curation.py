"""Compare recorded cycle gross sales using fixed facility-group OOF splits."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gc
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import time
import traceback

for variable in ["OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"]:
    os.environ[variable] = "2"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402 -- limit native threads before numerical imports
import pandas as pd  # noqa: E402

from scripts import run_limix_benchmark as engine  # noqa: E402
from scripts.train_adp_timing import load_limix  # noqa: E402
from src.regional_curation_model import (CLASSICAL, FEATURES, NUMERIC, SEED, TARGET,  # noqa: E402
    assign_folds, classical_predictions, features, prepare_rows, summarize_predictions)

METRICS = ROOT / "artifacts/regional_curation_metrics.json"
REPORT = ROOT / "reports/regional_curation_experiment.md"
LIMITATIONS = [
    "Target is recorded crop-cycle gross sales in KRW, not profit, independently audited income or causal adoption benefit.",
    "1274 of 1474 source records have missing sales; the positive recorded-sales cohort is selected, not representative of all farms.",
    "Source area definition pyeong conflicts with exact API m2 matches, so no area variable enters this primary comparison.",
    "Actual recorded planting year/month and facility metadata proxy planned pre-adoption inputs; availability at adoption is unverified.",
    "Five crops are pooled, not separately trained; facility IDs may have unknown aliases or shared ownership.",
    "Facility GroupKFold is not future-year validation. Models reuse OOF data; there is no untouched final evaluation set.",
    "The extreme recorded sale remains in the primary comparison; explicit sensitivity exclusion is not a correction or preferred score.",
    "No farm cost or investment target is available, so these models are not an ROI or deployment validation.",
]


def read_inputs():
    candidate = ROOT / "data/processed/regional_curation_candidates.csv"
    manifest_path = ROOT / "data/processed/regional_curation_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = manifest["outputs"][candidate.name]
    if engine.sha256(candidate) != expected["sha256"] or candidate.stat().st_size != expected["bytes"]:
        raise ValueError("Regional candidates differ from preparation manifest")
    source = ROOT / manifest["source"]
    if engine.sha256(source) != manifest["source_sha256"]:
        raise ValueError("Regional source XLSX changed")
    if manifest["primary_feature_whitelist"] != FEATURES or manifest["target"] != TARGET:
        raise ValueError("Regional model contract differs from preparation")
    rows, audit = prepare_rows(pd.read_csv(candidate, encoding="utf-8-sig"))
    if len(rows) != manifest["statistics"]["eligible_rows"]:
        raise ValueError("Candidate row count differs from preparation")
    rows["fold"] = assign_folds(rows)
    studies = {"primary_recorded": rows,
               "sensitivity_without_flagged_extreme": rows.loc[~rows["large_revenue_review_flag"]].copy()}
    paths = [candidate, manifest_path, source]
    hashes = {str(path.relative_to(ROOT)): engine.sha256(path) for path in paths}
    return studies, audit, hashes, manifest


def fold_records(rows):
    records = []
    for fold in range(5):
        train, query = rows.loc[rows["fold"].ne(fold)], rows.loc[rows["fold"].eq(fold)]
        if train.empty or query.empty:
            raise ValueError("Empty study fold")
        if set(train["facility_id"]) & set(query["facility_id"]):
            raise ValueError("Facility group leakage")
        records.append({"fold": fold, "n_train": len(train), "n_test": len(query),
                        "train_facilities": int(train["facility_id"].nunique()),
                        "test_facilities": int(query["facility_id"].nunique()),
                        "train_ids": train["source_row_id"].tolist(),
                        "test_ids": query["source_row_id"].tolist(), "group_overlap": False})
    return records


def check_regression_path(predictor, train, query, study, fold):
    """Exercise the actual V2 path, preserving train context under altered queries."""
    import torch

    x_train, x_query = features(train).to_numpy(object), features(query).to_numpy(object)
    changed = x_query.copy()
    for column, name in enumerate(FEATURES):
        changed[:, column] = 1_000_000 if name in NUMERIC else "__unseen_query_category__"
    snapshots = []
    for query_values in [x_query, changed]:
        inputs, standardized_y = predictor._prepare_reg_context(
            x_train, train[TARGET].to_numpy(float), query_values)
        contexts = []
        for index, (values, categories) in enumerate(inputs):
            transformed, transformed_y, _ = predictor.get_xy_reg(
                values.copy(), index, standardized_y.copy(), predictor.preprocess_pipelines[index],
                categories.copy(), "Regression", unique_dataset_name=f"regional_check_{study}_{fold}")
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
    return {"study": study, "fold": fold, "pipelines_checked": len(snapshots[0]),
            "training_transforms_query_invariant": True, "internal_normalization_query_invariant": True,
            "heldout_targets_passed": False}


def oof_path(study):
    return ROOT / f"artifacts/regional_curation_{study}_oof.csv"


def write_report(result):
    audit = result["cohort_audit"]
    lines = ["# 지역별 농가 작기 총매출 모델 비교", "", "Built with StableAI LimiX.", "",
             f"상태: **{result['status']}**. 실제 기록 총매출 **원/작기**를 대상으로 "
             f"**{audit['included_rows']}개 작기, {audit['facility_groups']}개 시설**을 비교했다. "
             "매출에서 비용을 빼지 않았으므로 순이익·ROI·스마트팜 도입 효과가 아니다.", "",
             "## 자료와 입력", "",
             "1,474개 원행 중 매출 결측이 1,274행이며, 양의 매출은 200행이다. "
             "범위 밖 품목 1행과 식별이 모호한 양의 매출 7행을 제외한 192행을 사용한다. "
             "미기록 매출을 0으로 채우지 않는다. 5품목을 함께 학습하며 표본이 대표성 있게 추출된 자료는 아니다.", "",
             "입력은 품목·품종·시도·시군구·시설유형·정식 연월이다. 실제 관측 정식 연월을 앞으로의 "
             "계획 일정의 대리 입력으로 쓴다. 종료일·작기 길이·출하량·등급·매출·시설ID·감사 플래그는 "
             "입력에서 제외한다. 특히 원자료 면적은 정의서 평과 API ㎡가 충돌하므로 사용하지 않는다. "
             "정확한 API 연결로 확인한 면적은 감사 증거로만 보존한다.", "",
             "품목 분포: " + json.dumps(audit["crop_counts"], ensure_ascii=False), "",
             "정식연도 분포: " + json.dumps(audit["planting_year_counts"], ensure_ascii=False), "",
             "## 검증", "",
             "시설별 GroupKFold 5개를 고정하고 모든 모델을 같은 원행에서 평가했다. "
             "품목 중앙값 및 품목×정식월 중앙값(품목→전체 중앙값 순으로 대체), CatBoost MAE, "
             "XGBoost absoluteerror, 실제 400M LimiX를 비교한다. 학습 폴드만으로 전처리·중앙값을 적합한다. "
             "시설 분리는 미래 연도 검증이 아니며 모델 선택용 비교와 별개인 최종 검증셋은 없다."]
    for study, label in [("primary_recorded", "원값 포함 주 결과"),
                         ("sensitivity_without_flagged_extreme", "플래그 극단값 제외 민감도")]:
        lines += ["", f"## {label}", "", "| 방법 | 행 | MAE(원) | RMSE(원) | 절대오차 중앙값(원) |",
                  "|---|---:|---:|---:|---:|"]
        for name, score in result["studies"][study].get("models", {}).items():
            lines.append(f"| {name} | {score['n_scored']} | {score['mae_krw']:,.0f} | {score['rmse_krw']:,.0f} | "
                         f"{score['median_absolute_error_krw']:,.0f} |")
    lines += ["", "주 결과에는 **233,563,333,310원** 기록도 원값 그대로 포함한다. "
              "민감도는 사전 감사의 100억 원 초과 검토 플래그 1행만 각 학습/검증 구간에서 제외하고 "
              "원래 폴드를 유지해 다시 적합한 결과다. 원기록 오류를 확정하거나 더 좋은 점수를 선택한 것이 아니다.", "",
              "검토 원행: " + json.dumps(audit["outlier_review_rows"], ensure_ascii=False), "",
              "## 해석 한계와 재현", "",
              "양의 매출이 기록된 농가만 포함되어 실패·누락·미응답 농가의 경제성을 설명하지 못한다. "
              "실제 원자료 정의는 작기 총매출이나 기록 완결성이 독립적으로 검증된 것은 아니다. "
              "다른 시설 ID로 표시된 같은 소유자·시설을 알 수 없고 사전 메타데이터 확정 시점도 모른다. "
              "이 예측을 도입 전 수익 보장 또는 검증된 투자 판단으로 배포하지 않는다.", "",
              "`.venv/Scripts/python.exe -X utf8 scripts/train_regional_curation.py --stage classical`", "",
              "`.venv-limix/Scripts/python.exe -X utf8 scripts/train_regional_curation.py --stage limix`", "",
              "`artifacts/regional_curation_metrics.json`에 원자료/코드 해시, 폴드별 원행 ID, 품목별·폴드별 점수, "
              "패키지 버전·실행시간을 보존한다. `regional_curation_*_oof.csv`는 실제값과 행별 검증 예측이다. "
              "LimiX는 기존 공식 체크포인트와 검토된 train-only 전처리 패치를 재사용한다. "
              "각 폴드의 실제 V2 회귀 경로·내부 정규화에서 검증 입력을 변조해 학습 변환 불변성을 확인한다."]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(stage):
    started = time.perf_counter()
    studies, audit, hashes, manifest = read_inputs()
    source_hashes = {name: engine.sha256(ROOT / name) for name in [
        "src/regional_curation_model.py", "scripts/train_regional_curation.py",
        "scripts/train_adp_timing.py", "scripts/run_limix_benchmark.py"]}
    splits = {study: fold_records(rows) for study, rows in studies.items()}
    if stage == "classical":
        result = {"status": "running", "started_at_utc": datetime.now(timezone.utc).isoformat(),
                  "target": TARGET, "features": FEATURES, "seed": SEED, "input_sha256": hashes,
                  "cohort_audit": audit, "source_statistics": manifest["statistics"], "limitations": LIMITATIONS,
                  "split": "GroupKFold(n_splits=5, shuffle=False); sensitivity preserves primary assignments",
                  "studies": {name: {"folds": records, "models": {}} for name, records in splits.items()}, "stages": {}}
        oofs = {study: rows[["source_row_id", "cycle_id", "facility_id", "crop", "planting_year",
                            TARGET, "large_revenue_review_flag", "fold"]].copy() for study, rows in studies.items()}
        for oof in oofs.values():
            for name in CLASSICAL:
                oof[name] = np.nan
        names = CLASSICAL
    else:
        result = json.loads(METRICS.read_text(encoding="utf-8"))
        if result["input_sha256"] != hashes or result["stages"].get("classical", {}).get("status") != "completed":
            raise ValueError("Run classical stage first with exact current inputs")
        if result["stages"]["classical"]["source_sha256"] != source_hashes:
            raise ValueError("Model source changed since classical stage")
        oofs = {}
        for study, rows in studies.items():
            saved = result["studies"][study]
            if saved["folds"] != splits[study] or saved["oof_sha256"] != engine.sha256(oof_path(study)):
                raise ValueError("Saved split or OOF artifact changed")
            oof = pd.read_csv(oof_path(study), encoding="utf-8-sig")
            if (oof["source_row_id"].tolist() != rows["source_row_id"].tolist()
                    or not np.array_equal(oof[TARGET], rows[TARGET])
                    or not np.array_equal(oof["fold"], rows["fold"])):
                raise ValueError("OOF identity, target or fold changed")
            oof.index = rows.index
            oof["limix_2_400m"] = np.nan
            saved["models"].pop("limix_2_400m", None)
            oofs[study] = oof
        names = CLASSICAL + ["limix_2_400m"]
    result["status"] = "running"
    result["stages"][stage] = {"status": "running", "folds_completed": 0, "source_sha256": source_hashes}
    engine.write_json(METRICS, result)
    predictor = None
    try:
        if stage == "limix":
            predictor, metadata = load_limix()
            result["limix"] = {**metadata, "regression_path_checks": []}
        timings = []
        for study, rows in studies.items():
            oof = oofs[study]
            for fold in range(5):
                train, query = rows.loc[rows["fold"].ne(fold)], rows.loc[rows["fold"].eq(fold)]
                fold_started = time.perf_counter()
                print(f"{stage} {study} fold={fold} train={len(train)} test={len(query)}", flush=True)
                if predictor is None:
                    predicted = classical_predictions(train, query)
                else:
                    check = check_regression_path(predictor, train, query, study, fold)
                    result["limix"]["regression_path_checks"].append(check)
                    values = predictor.predict(features(train).to_numpy(object), train[TARGET].to_numpy(float),
                                               features(query).to_numpy(object), task_type="Regression",
                                               unique_dataset_name=f"regional_{study}_{fold}")
                    predicted = {"limix_2_400m": np.maximum(np.asarray(values, dtype=float).reshape(-1), 0)}
                for name, values in predicted.items():
                    if len(values) != len(query) or not np.isfinite(values).all():
                        raise ValueError(f"Invalid predictions: {study}/{name}/{fold}")
                    oof.loc[query.index, name] = values
                timings.append({"study": study, "fold": fold, "seconds": time.perf_counter() - fold_started})
                result["stages"][stage]["folds_completed"] += 1
                oof.to_csv(oof_path(study), index=False, encoding="utf-8-sig")
                engine.write_json(METRICS, result)
            result["studies"][study]["models"] = summarize_predictions(oof, names)
            result["studies"][study]["oof_sha256"] = engine.sha256(oof_path(study))
        packages = (["numpy", "pandas", "scikit-learn", "catboost", "xgboost"] if stage == "classical"
                    else ["numpy", "pandas", "scikit-learn", "torch"])
        result["stages"][stage].update(status="completed", total_seconds=time.perf_counter() - started,
            fold_timings=timings, packages={name: importlib.metadata.version(name) for name in packages})
        if stage == "limix":
            result["limix"]["preprocessing_protocol"] = "train_only_regression_v2"
        result["status"] = "completed" if stage == "limix" else "awaiting_limix"
        result["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
        engine.write_json(METRICS, result)
        write_report(result)
        print(json.dumps({study: {name: values["mae_krw"] for name, values in record["models"].items()}
                          for study, record in result["studies"].items()}, ensure_ascii=False), flush=True)
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
        failed = json.loads(METRICS.read_text(encoding="utf-8")) if METRICS.exists() else {}
        failure = {"stage": args.stage, "time_utc": datetime.now(timezone.utc).isoformat(),
                   "error_type": type(error).__name__, "error": str(error), "traceback": traceback.format_exc()}
        failed.update(status="failed", last_failure=failure)
        failed.setdefault("stages", {}).setdefault(args.stage, {}).update(status="failed", failure=failure)
        engine.write_json(METRICS, failed)
        raise
