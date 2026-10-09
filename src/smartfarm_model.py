"""Initial RDA aggregate benchmark models, not individual smart-farm effects."""

from __future__ import annotations

import json
import math
import hashlib
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from catboost import CatBoostRegressor
from sklearn.compose import ColumnTransformer
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder
from xgboost import XGBRegressor


FEATURES = ["year", "crop", "cultivation_type", "region"]
TARGET = "yield_kg_per_1000m2"
CASE_KEYS = ["year", "crop", "cultivation_type", "region", "period_basis", "source_category"]
MIN_TRAIN_ROWS = 20
MIN_TEST_ROWS = 5


def load_rda(paths: list[Path]) -> tuple[pd.DataFrame, dict[str, Any]]:
    if not paths:
        raise ValueError("No real RDA CSV files found")
    data = pd.concat([pd.read_csv(path, encoding="utf-8-sig") for path in paths], ignore_index=True)
    required = set(FEATURES + [TARGET, "period_basis", "source_url", "source_file"])
    missing = required - set(data.columns)
    if missing:
        raise ValueError(f"Missing RDA columns: {sorted(missing)}")
    original_count = len(data)
    for column in ["crop", "cultivation_type", "region", "period_basis"]:
        data[column] = data[column].fillna("").astype(str).str.strip()
    if "source_category" not in data:
        data["source_category"] = data["crop_original"] if "crop_original" in data else data["cultivation_type"]
    data["source_category"] = data["source_category"].fillna("").astype(str)
    data["year"] = pd.to_numeric(data["year"], errors="coerce")
    data[TARGET] = pd.to_numeric(data[TARGET], errors="coerce")
    valid = (
        data["year"].notna()
        & (data["year"] % 1 == 0)
        & np.isfinite(data[TARGET])
        & (data[TARGET] > 0)
        & data[["crop", "cultivation_type", "region", "period_basis", "source_category"]].ne("").all(axis=1)
    )
    invalid_count = int((~valid).sum())
    data = data.loc[valid].copy()
    data["year"] = data["year"].astype(int)
    conflicts = data.groupby(CASE_KEYS, dropna=False)[TARGET].nunique()
    if (conflicts > 1).any():
        raise ValueError("Conflicting yield values for the same RDA year/crop/type/region/source category")
    duplicate_count = int(data.duplicated(CASE_KEYS).sum())
    data = data.drop_duplicates(CASE_KEYS).copy()
    national = data["region"].isin(["전국", "전국평균", "전국 평균", "national", "National"])
    data["geographic_scope"] = np.where(national, "national", "regional")
    # Survey classification changed in 2023. Separate regimes prevent historical
    # forcing/retarding crop categories from being treated as soil/hydroponic.
    data["classification_regime"] = data["schema_regime"] if "schema_regime" in data else np.where(data["year"] >= 2023, "2023_onward", "before_2023")
    return data, {
        "input_files": [str(path) for path in paths],
        "input_sha256": {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths},
        "input_rows": original_count,
        "invalid_rows_excluded": invalid_count,
        "duplicate_rows_excluded": duplicate_count,
        "valid_rows": len(data),
    }


def chronological_split(data: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, int]:
    if data.empty:
        raise ValueError("Cannot split an empty dataset")
    cutoff = int(data["year"].max())
    train = data.loc[data["year"] < cutoff].copy()
    test = data.loc[data["year"] == cutoff].copy()
    return train, test, cutoff


def build_features(data: pd.DataFrame) -> pd.DataFrame:
    result = data.loc[:, FEATURES].copy()
    for column in FEATURES[1:]:
        result[column] = result[column].fillna("unknown").astype(str)
    result["year"] = result["year"].astype(int)
    return result


def baseline_predict(history: pd.DataFrame, queries: pd.DataFrame, latest: bool = False) -> np.ndarray:
    """Exact same source category and crop; no cross-crop global fallback."""
    estimates = []
    for _, query in queries.iterrows():
        candidates = history.loc[
            (history["year"] < int(query["year"]))
            & (history["crop"] == query["crop"])
            & (history["cultivation_type"] == query["cultivation_type"])
            & (history["source_category"] == query["source_category"])
            & (history["region"] == query["region"])
        ]
        if candidates.empty:
            estimates.append(float("nan"))
            continue
        if latest:
            candidates = candidates.loc[candidates["year"] == candidates["year"].max()]
        estimates.append(float(candidates[TARGET].median()))
    return np.asarray(estimates)


def _models() -> dict[str, Any]:
    return {
        "catboost": CatBoostRegressor(
            iterations=250, depth=4, learning_rate=0.04, loss_function="RMSE",
            random_seed=42, verbose=False, allow_writing_files=False, thread_count=2,
            cat_features=FEATURES[1:],
        ),
        "xgboost": Pipeline([
            ("encode", ColumnTransformer([
                ("category", OneHotEncoder(handle_unknown="ignore", sparse_output=False), FEATURES[1:]),
                ("year", "passthrough", ["year"]),
            ])),
            ("regressor", XGBRegressor(
                n_estimators=200, max_depth=3, learning_rate=0.04, min_child_weight=3,
                objective="reg:squarederror", random_state=42, n_jobs=2,
            )),
        ]),
    }


def _metric(actual: np.ndarray, predictions: np.ndarray) -> dict[str, Any]:
    mask = np.isfinite(predictions)
    if not mask.any():
        return {"n_scored": 0, "mae_kg_per_1000m2": None, "rmse_kg_per_1000m2": None}
    return {
        "n_scored": int(mask.sum()),
        "mae_kg_per_1000m2": float(mean_absolute_error(actual[mask], predictions[mask])),
        "rmse_kg_per_1000m2": float(math.sqrt(mean_squared_error(actual[mask], predictions[mask]))),
    }


def train_initial(data: pd.DataFrame, artifact_dir: Path) -> dict[str, Any]:
    """Compare latest-year holdout, then refit all observations for future use."""
    artifact_dir.mkdir(parents=True, exist_ok=True)
    groups = []
    prediction_frames = []
    scopes = ["geographic_scope", "classification_regime", "period_basis"]
    for number, (group_keys, group_data) in enumerate(data.groupby(scopes, sort=True)):
        scope, regime, period = group_keys
        train, test, cutoff = chronological_split(group_data)
        result: dict[str, Any] = {
            "group_id": f"rda_{number}", "geographic_scope": scope,
            "classification_regime": regime, "period_basis": period,
            "n_rows": len(group_data), "n_train": len(train), "n_test": len(test),
            "train_years": sorted(int(year) for year in train["year"].unique()),
            "holdout_year": cutoff, "metrics": {}, "artifact_files": {},
            "source_categories": sorted(group_data["source_category"].unique().tolist()),
            "unsupported_holdout_rows": 0,
        }
        if train.empty:
            result["status"] = "insufficient_history_no_training"
            groups.append(result)
            continue
        median_predictions = baseline_predict(train, test)
        latest_predictions = baseline_predict(train, test, latest=True)
        # No candidate receives credit for a crop/type absent from training.
        support = np.isfinite(median_predictions)
        result["unsupported_holdout_rows"] = int((~support).sum())
        actual = test[TARGET].to_numpy(dtype=float)
        pred_frame = test[CASE_KEYS + [TARGET, "source_file", "source_url"]].copy()
        pred_frame["group_id"] = result["group_id"]
        pred_frame["supported_by_training"] = support
        pred_frame["historical_median_prediction"] = median_predictions
        pred_frame["latest_prior_prediction"] = latest_predictions
        result["metrics"]["historical_median"] = _metric(actual, median_predictions)
        result["metrics"]["latest_prior"] = _metric(actual, latest_predictions)
        enough = len(train) >= MIN_TRAIN_ROWS and int(support.sum()) >= MIN_TEST_ROWS
        result["status"] = "initial_aggregate_comparison" if enough else "insufficient_rows_for_ml_comparison"
        models = _models() if enough else {}
        fitted_artifacts = {}
        for name, model in models.items():
            model.fit(build_features(train), train[TARGET])
            predictions = np.maximum(0, np.asarray(model.predict(build_features(test)), dtype=float))
            predictions[~support] = np.nan
            pred_frame[name + "_prediction"] = predictions
            result["metrics"][name] = _metric(actual, predictions)
            model.fit(build_features(group_data), group_data[TARGET])
            fitted_artifacts[name] = model
        valid_metrics = {name: metric for name, metric in result["metrics"].items() if metric["n_scored"] > 0}
        selected = min(valid_metrics, key=lambda name: valid_metrics[name]["mae_kg_per_1000m2"]) if valid_metrics else "historical_median"
        artifact_file = artifact_dir / (result["group_id"] + ".pkl")
        joblib.dump({
            "model_kind": "RDA aggregate reference; not individual farm/equipment effect",
            "selected_model": selected, "models": fitted_artifacts,
            "history": group_data, "features": FEATURES, "metadata": result,
        }, artifact_file)
        result["selected_on_holdout"] = selected
        result["artifact_files"]["bundle"] = str(artifact_file.resolve())
        prediction_frames.append(pred_frame)
        groups.append(result)
    if prediction_frames:
        pd.concat(prediction_frames, ignore_index=True).to_csv(artifact_dir / "holdout_predictions.csv", index=False, encoding="utf-8-sig")
    result = {
        "target": TARGET, "features": FEATURES,
        "purpose": "Interim regional/crop aggregate reference prediction, not a farm-level smart-farm adoption model",
        "validation": "Latest-year holdout per survey regime/period/scope. No random row split. Selection holdout is not an independent final test.",
        "limitations": [
            "National and regional aggregates are fitted separately; regional survey examples are not statistically representative estimates.",
            "Survey categories before and since 2023 are fitted separately; source_category is retained for support checks.",
            "Neither investment cost nor equipment productivity uplift is learned from these records.",
            "Only a few yearly observations are available; metrics do not establish accuracy for a new individual farm.",
        ],
        "groups": groups,
    }
    (artifact_dir / "model_metrics.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def predict_yield(bundle_path: str | Path, query: dict[str, Any]) -> dict[str, Any]:
    """Predict a future aggregate reference for an observed crop/type/region.

    Query: year,crop,cultivation_type,region,source_category. Load only our local
    generated bundle: pickle/joblib files are executable and not upload inputs.
    """
    bundle = joblib.load(bundle_path)
    history = bundle["history"]
    if int(query["year"]) <= int(history["year"].max()):
        raise ValueError("Future query year must be after the artifact's latest training year")
    matches = history.loc[
        (history["crop"] == query["crop"])
        & (history["cultivation_type"] == query["cultivation_type"])
        & (history["region"] == query["region"])
        & (history["source_category"] == query["source_category"])
    ]
    if matches.empty:
        return {"status": "unsupported_conditions", "yield_kg_per_1000m2": None, "n_reference_rows": 0}
    frame = pd.DataFrame([query])
    name = bundle["selected_model"]
    if name in {"historical_median", "latest_prior"}:
        estimate = float(baseline_predict(history, frame, latest=name == "latest_prior")[0])
    else:
        estimate = max(0, float(bundle["models"][name].predict(build_features(frame))[0]))
    return {
        "status": "aggregate_reference_only", "yield_kg_per_1000m2": estimate,
        "model": name, "n_reference_rows": len(matches),
        "latest_source_year": int(matches["year"].max()),
        "period_basis": bundle["metadata"]["period_basis"],
        "warning": "Regional/crop survey reference, not a prediction validated for an individual prospective farm or a causal installation effect",
    }


def write_report(metrics: dict[str, Any], audit: dict[str, Any], path: Path) -> None:
    lines = [
        "# 실제 농사로 집계자료 기반 초기 모델", "",
        "이 실험은 지역·품목별 집계 수량의 다음 관측연도 예측을 비교한다. 개별 농가 스마트팜 도입효과·수익률 모델은 아니다.",
        "2023년 조사 분류 변경 전후, 전국·지역, 기작 단위를 분리했다. 지역 자료는 지역 소득조사 사례이며 통계적 대표성을 주장하지 않는다.",
        "", f"원본 CSV {len(audit['input_files'])}개, 유효 행 {audit['valid_rows']}개. 무효 제외 {audit['invalid_rows_excluded']}행, 중복 제외 {audit['duplicate_rows_excluded']}행.",
        "입력: 연도·품목·재배형태·지역. 매출·가격·생육·환경 등 목표 수량을 역산하거나 도입 후에만 알 수 있는 값은 사용하지 않는다.",
        "각 범위의 가장 최근 연도를 보류하고 이전 연도만 학습했다. 같은 보류 자료로 모델을 비교·선택했으므로 독립적인 최종 검증 결과가 아니다.",
        "", "| 범위 / 분류 / 단위 | 학습·검증 행 | 모델 | MAE (kg/10a) | RMSE (kg/10a) | 평가 행 |", "|---|---:|---|---:|---:|---:|",
    ]
    for group in metrics["groups"]:
        label = f"{group['geographic_scope']} / {group['classification_regime']} / {group['period_basis']}"
        if not group["metrics"]:
            lines.append(f"| {label} | {group['n_train']} / {group['n_test']} | 과거 자료 부족 | — | — | 0 |")
        for name, metric in group["metrics"].items():
            mae = "—" if metric["mae_kg_per_1000m2"] is None else f"{metric['mae_kg_per_1000m2']:.2f}"
            rmse = "—" if metric["rmse_kg_per_1000m2"] is None else f"{metric['rmse_kg_per_1000m2']:.2f}"
            lines.append(f"| {label} | {group['n_train']} / {group['n_test']} | {name} | {mae} | {rmse} | {metric['n_scored']} |")
    lines += [
        "",
        "CatBoost/XGBoost 비교 최소 기준은 학습 20행·동일 품목/재배분류 지원 검증 5행이다. 기준 미달 시 과거값 비교만 제시하며 모델 성능을 만들지 않는다.",
        "최신 자료까지 재학습한 로컬 묶음은 artifacts/rda_*.pkl, 검증 예측값은 artifacts/holdout_predictions.csv에 저장한다. 모델 선택에 쓴 검증 예측과 전체 자료 재학습 모델을 구별한다.",
        "", "## 경제성 계산", "",
        "실제 견적은 아직 필수 입력이다. 0원으로 대체하지 않는다. 출하량·농가수취단가·현금비용 배수는 명시적 가정이며 통계적 신뢰구간이 아니다.",
        "경영비에 포함된 감가상각은 소득 계산에서 차감하고 현금흐름 계산에서는 제거한다. 초기 투자와 교체 투자는 각 현금 지출 연도에만 차감한다. 기존 시설 개량은 도입 후 현금흐름과 기존 유지 현금흐름의 차이를 투자비와 비교한다.",
        "세금·금융조달·보조금·운전자금 증감·기말 처분가치는 현재 계산에서 제외하며 결과에도 표시한다. 가족노동 기회비용은 현금비용과 별도로 표시한다.",
        "", "## 남은 실제 자료", "",
        "대회 미개방 농가별 시설·경영 원자료, 승인된 스마트팜 API 원자료, 계획 장비의 실제 설치 견적·유지비·기존 운영 기준을 확보해야 개별 도입 판단의 근거를 보강할 수 있다. 현재 집계자료는 그 대체 완료를 뜻하지 않는다.",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
