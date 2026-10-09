"""Compare recorded strawberry cycle kg with fixed facility-group OOF splits."""

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

import numpy as np  # noqa: E402 -- set numerical thread limits first
import pandas as pd  # noqa: E402

from scripts import run_limix_benchmark as engine  # noqa: E402
from scripts.train_adp_timing import load_limix  # noqa: E402
from src.strawberry_curation_model import (CLASSICAL, FEATURES, NUMERIC, SEED, TARGET,  # noqa: E402
    assign_folds, classical_predictions, features, prepare_rows, summarize_predictions)

METRICS = ROOT / "artifacts/strawberry_curation_metrics.json"
REPORT = ROOT / "reports/strawberry_curation_experiment.md"
LIMITATIONS = [
    "Only positive recorded targets with nonconflicting periods and exactly matched positive API area are included.",
    "Zero quantities have unknown missingness semantics; this selected cohort is not representative of all farms or failures.",
    "Target is the recorded crop-cycle shipment total in kg, not independently certified full harvest or annual yield.",
    "Metadata availability before adoption is unverified; actual planting month/day proxy a future planned date.",
    "Facility IDs group all observed cycles, but aliases and shared owners across IDs are unverified.",
    "GroupKFold estimates held-out observed facility performance, not future-year, causal installation, or economic performance.",
    "Comparisons reuse the same OOF data; no model has an untouched final evaluation set or deployment validation.",
    "Primary evaluation retains the extreme raw target. Sensitivity removal is an explicit data-review scenario, not a correction.",
    "No cost, revenue, annualization, or investment payback target is inferred.",
]


def read_inputs():
    candidate_path = ROOT / "data/processed/strawberry_curation_candidates.csv"
    audit_path = ROOT / "data/processed/strawberry_curation_audit.json"
    source_audit = json.loads(audit_path.read_text(encoding="utf-8"))
    expected = source_audit["output_files"][candidate_path.name]
    if engine.sha256(candidate_path) != expected["sha256"] or candidate_path.stat().st_size != expected["bytes"]:
        raise ValueError("Candidate file differs from its preparation audit")
    paths = [candidate_path, audit_path, Path(source_audit["source"]["zip_path"])]
    if engine.sha256(paths[-1]) != source_audit["source"]["zip_sha256"]:
        raise ValueError("Curation archive SHA mismatch")
    for name in ["smartfarm_api_cycles.csv", "smartfarm_api_catalog.csv"]:
        path = ROOT / "data/processed" / name
        if engine.sha256(path) != source_audit["api_metadata_source"][name]["sha256"]:
            raise ValueError(f"API metadata source changed: {name}")
        paths.append(path)
    if set(source_audit["feature_columns"]) != set(FEATURES):
        raise ValueError("Feature allowlist differs from preparation audit")
    candidates = pd.read_csv(candidate_path, encoding="utf-8-sig")
    if len(candidates) != expected["rows"]:
        raise ValueError("Candidate row count mismatch")
    rows, cohort_audit = prepare_rows(candidates)
    rows["fold"] = assign_folds(rows)
    studies = {"primary_recorded": rows,
               "sensitivity_without_flagged_extreme": rows.loc[~rows["outlier_review"]].copy()}
    hashes = {str(path.relative_to(ROOT)): engine.sha256(path) for path in paths}
    return studies, cohort_audit, hashes, source_audit


def fold_records(rows):
    records = []
    for fold in range(5):
        train, query = rows.loc[rows["fold"].ne(fold)], rows.loc[rows["fold"].eq(fold)]
        if train.empty or query.empty:
            raise ValueError("An analytic study has an empty fold")
        if set(train["farm_group"]) & set(query["farm_group"]):
            raise ValueError("Facility leakage in study")
        records.append({"fold": fold, "n_train": len(train), "n_test": len(query),
                        "train_facilities": int(train["farm_group"].nunique()),
                        "test_facilities": int(query["farm_group"].nunique()),
                        "train_ids": train["source_record_id"].tolist(),
                        "test_ids": query["source_record_id"].tolist(), "group_overlap": False})
    return records


def check_regression_path(predictor, train, query, study, fold):
    """Exercise real V2 preprocessing and internal normalization on altered queries."""
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
                categories.copy(), "Regression", unique_dataset_name=f"strawberry_check_{study}_{fold}")
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
    return ROOT / f"artifacts/strawberry_curation_{study}_oof.csv"


def write_report(result):
    audit = result["cohort_audit"]
    lines = ["# 딸기 큐레이션: 기록된 작기 총출하량 비교", "", "Built with StableAI LimiX.", "",
             f"상태: **{result['status']}**. 타깃은 공식 정의서상 **한 작기의 총출하수량(kg)**이다. "
             "실제 자료의 완결성이 별도로 인증된 것은 아니며 연간 수량·도입 효과·경제성 예측이 아니다.", "",
             f"정제 후보 {audit['candidate_rows']}행 중 API 작기·카탈로그와 정확히 연결되고 양의 ㎡ 면적이 있는 "
             f"**{audit['included_rows']}작기·{audit['facility_groups']}시설**을 공통 코호트로 사용했다. "
             "다른 행을 추가해 특정 모델만 유리한 비교를 하지 않았다.", "",
             "## 입력과 평가", "",
             "입력은 확인된 면적(㎡), 정식 월·일, 품종, 시도·시군구, 시설 유형, 재배방식, 온실 형태다. "
             "정식 연도·실제 종료일·작기 길이·시설ID·출하 등급·금액·관측 환경/생육·품질 플래그는 입력하지 않는다. "
             "실제 정식 일정과 관측 시설 특성이 도입 전에 확정된 계획이라는 증거는 없어 대리 입력으로만 해석한다.", "",
             "같은 시설의 여러 작기는 항상 같은 검증 폴드에 둔 GroupKFold 5개를 사용했다. "
             "전처리·중앙값은 각 학습 폴드만 사용한다. 총량 중앙값, 정식월 중앙값, "
             "학습자료 kg/㎡ 중앙값×검증 시설 면적 기준선과 CatBoost/XGBoost/LimiX를 같은 행에서 평가한다. "
             "이 분할은 미래 연도 검증이 아니며 별도 최종 평가셋은 없다.", "",
             "품종 분포: " + json.dumps(audit["variety_counts"], ensure_ascii=False), "",
             "정식연도 분포: " + json.dumps(audit["planting_year_counts"], ensure_ascii=False), "",
             "## 원기록 전체 결과", "",
             "주 결과에는 확인이 필요한 **14,604,000kg** 기록도 그대로 포함한다. "
             "성능을 좋게 만들기 위해 수량을 수정·축소·합산하거나 행을 숨기지 않았다."]
    for study, label in [("primary_recorded", "주 결과: 극단값 포함"),
                         ("sensitivity_without_flagged_extreme", "민감도: 검토 플래그가 있는 극단값만 제외")]:
        lines += ["", f"### {label}", "", "| 방법 | 행 | MAE(kg) | RMSE(kg) | 오차 절댓값 중앙값(kg) |",
                  "|---|---:|---:|---:|---:|"]
        for name, score in result["studies"][study].get("models", {}).items():
            lines.append(f"| {name} | {score['n_scored']} | {score['mae_kg']:,.2f} | "
                         f"{score['rmse_kg']:,.2f} | {score['median_absolute_error_kg']:,.2f} |")
    lines += ["", "민감도 실험은 원래 시설별 폴드배치를 고정하고 플래그 행만 각 학습/검증 구간에서 제외해 "
              "다시 적합한 결과다. 원기록이 오류임을 확정하거나 민감도 점수를 주 성능으로 채택한 것이 아니다.", "",
              "검토 대상 원행: " + json.dumps(audit["outlier_review_rows"], ensure_ascii=False), "",
              "## 한계", "",
              "0kg를 실패농가로 확정할 수 없어 제외했다. 따라서 양의 기록이 있는 농가에 편중된 자료이며 "
              "실패 확률이나 모든 신규 농가의 기대수량을 나타내지 않는다. 자료의 기록 완결성, 시설 ID의 "
              "다른 별칭, 관측 메타데이터의 사전 확정 시점도 미확정이다. 수익금액의 회계상 의미·비용·투자비가 "
              "확인되지 않았으므로 경제성 계산에 이 예측을 자동 연결하지 않는다.", "",
              "## 재현과 산출물", "",
              "`.venv/Scripts/python.exe -X utf8 scripts/train_strawberry_curation.py --stage classical`", "",
              "`.venv-limix/Scripts/python.exe -X utf8 scripts/train_strawberry_curation.py --stage limix`", "",
              "`artifacts/strawberry_curation_metrics.json`에 원자료/코드 해시, 폴드별 정확한 원행 ID, "
              "모든 점수, 라이브러리 버전, 단계별 상태와 실행 시간을 저장했다. "
              "`strawberry_curation_*_oof.csv`는 행별 원기록과 검증 예측이다. "
              "LimiX는 기존 공식 400M 체크포인트와 검토된 train-only 패치를 사용하고, 각 폴드의 실제 "
              "V2 회귀 경로와 내부 정규화에 쿼리 변조 검사를 적용한다. 사전학습 가중치를 갱신하지 않는다."]
    REPORT.write_text("\n".join(lines), encoding="utf-8")


def main(stage):
    started = time.perf_counter()
    studies, audit, hashes, source_audit = read_inputs()
    source_hashes = {name: engine.sha256(ROOT / name) for name in [
        "src/strawberry_curation_model.py", "scripts/train_strawberry_curation.py",
        "scripts/train_adp_timing.py", "scripts/run_limix_benchmark.py"]}
    splits = {study: fold_records(rows) for study, rows in studies.items()}
    if stage == "classical":
        result = {"status": "running", "started_at_utc": datetime.now(timezone.utc).isoformat(),
                  "target": TARGET, "features": FEATURES, "seed": SEED,
                  "input_sha256": hashes, "cohort_audit": audit, "source_tables": source_audit["tables"],
                  "source_exclusions": source_audit["exclusion_counts"], "limitations": LIMITATIONS,
                  "split": "GroupKFold(n_splits=5, shuffle=False); sensitivity preserves primary assignments",
                  "studies": {name: {"folds": records, "models": {}} for name, records in splits.items()},
                  "stages": {}}
        oofs = {study: rows[["source_record_id", "farm_group", "planting_year", "planting_date",
                            "area_m2", TARGET, "outlier_review", "fold"]].copy()
                for study, rows in studies.items()}
        for oof in oofs.values():
            for name in CLASSICAL:
                oof[name] = np.nan
        names = CLASSICAL
    else:
        result = json.loads(METRICS.read_text(encoding="utf-8"))
        if result["input_sha256"] != hashes or result["stages"].get("classical", {}).get("status") != "completed":
            raise ValueError("Run classical stage first on the exact inputs")
        if result["stages"]["classical"]["source_sha256"] != source_hashes:
            raise ValueError("Model source changed since classical comparison")
        oofs = {}
        for study, rows in studies.items():
            saved = result["studies"][study]
            if saved["folds"] != splits[study] or saved["oof_sha256"] != engine.sha256(oof_path(study)):
                raise ValueError("Saved split or OOF artifact changed")
            oof = pd.read_csv(oof_path(study), encoding="utf-8-sig")
            if (oof["source_record_id"].tolist() != rows["source_record_id"].tolist()
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
                                               unique_dataset_name=f"strawberry_{study}_{fold}")
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
        print(json.dumps({study: record["models"] for study, record in result["studies"].items()}, ensure_ascii=False), flush=True)
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
