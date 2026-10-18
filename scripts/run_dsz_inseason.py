"""Train or predict fixed-cutoff DSZ shipment updates entirely offline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from src.dsz_inseason import predict_inseason, train_inseason, write_json  # noqa: E402
from src.dsz_model import sha256  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    train = sub.add_parser("train", help="Compare seven planned inputs with same-cohort observation features")
    train.add_argument("--data-dir", type=Path, required=True, help="Prepared data with documented target periods")
    train.add_argument("--input-dir", type=Path, required=True, help="The exact raw export used for preparation")
    train.add_argument("--output-dir", type=Path, required=True, help="New directory; existing output is never overwritten")
    train.add_argument("--cutoff-days", type=int, default=30)
    train.add_argument("--window-days", type=int, default=28)
    train.add_argument("--crop", default="딸기")
    train.add_argument("--encoding", choices=["utf-8-sig", "cp949"], default="utf-8-sig")
    predict = sub.add_parser("predict", help="Use trusted locally generated model artifacts")
    predict.add_argument("--artifact-dir", type=Path, required=True)
    predict.add_argument("--input-dir", type=Path, required=True, help="Query facility and observation tables; management optional")
    predict.add_argument("--requests", type=Path, required=True, help="CSV containing plan_id,facility_id,cycle_id only")
    predict.add_argument("--output", type=Path, required=True)
    predict.add_argument("--encoding", choices=["utf-8-sig", "cp949"], default="utf-8-sig")
    args = parser.parse_args()
    if args.command == "train":
        result = train_inseason(args.data_dir, args.input_dir, args.output_dir, cutoff_days=args.cutoff_days,
                               window_days=args.window_days, crop=args.crop, encoding=args.encoding)
        print(json.dumps({key: result[key] for key in ["status", "data_kind", "rows", "facilities", "selected_methods"]}, ensure_ascii=False))
    else:
        metadata_path = args.output.with_suffix(".provenance.json")
        if args.output.exists() or metadata_path.exists():
            raise FileExistsError("Prediction or provenance output exists; choose a new output path")
        requests = pd.read_csv(args.requests, encoding=args.encoding, dtype=str, keep_default_na=False)
        result, metadata = predict_inseason(args.artifact_dir, args.input_dir, requests, encoding=args.encoding)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        result.to_csv(args.output, index=False, encoding="utf-8-sig")
        metadata.update(requests_sha256=sha256(args.requests), prediction_sha256=sha256(args.output), rows=len(result))
        write_json(metadata_path, metadata)
        print(json.dumps({"status": "completed", "rows": len(result), "data_kind": metadata["data_kind"],
                          "output": str(args.output.resolve())}, ensure_ascii=False))


if __name__ == "__main__":
    main()
