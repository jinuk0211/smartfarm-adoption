"""Run the archived KAMIS chronological price experiment and save audit outputs."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
from src.price_forecast import run_price_experiment  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "data/processed/kamis_wholesale_monthly_kg.csv")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "artifacts")
    arguments = parser.parse_args()
    result = run_price_experiment(pd.read_csv(arguments.input, encoding="utf-8-sig"))
    result["summary"]["input_sha256"] = hashlib.sha256(arguments.input.read_bytes()).hexdigest()
    result["summary"]["source_sha256"] = {
        name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        for name in ["src/price_forecast.py", "scripts/run_price_forecast.py"]
    }
    result["summary"]["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
    arguments.output_dir.mkdir(parents=True, exist_ok=True)
    output_hashes = {}
    for name in ["validation_predictions", "holdout_predictions", "forecast"]:
        path = arguments.output_dir / f"price_forecast_{name}.csv"
        result[name].to_csv(path, index=False, encoding="utf-8-sig")
        output_hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    result["summary"]["output_sha256"] = output_hashes
    (arguments.output_dir / "price_forecast_metrics.json").write_text(
        json.dumps(result["summary"], ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({key: result["summary"][key] for key in ["observed_kg_rows", "series_count", "holdout_selected", "holdout_baseline"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
