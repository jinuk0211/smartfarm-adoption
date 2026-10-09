"""Run from the project directory: .venv\\Scripts\\python scripts\\train_initial.py."""

import argparse
import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from src.smartfarm_model import load_rda, train_initial, write_report  # noqa: E402 -- direct-script project bootstrap


def main():
    parser = argparse.ArgumentParser(description="Train initial aggregate models on actual RDA records only")
    parser.add_argument("--data", type=Path, default=PROJECT / "data" / "processed")
    parser.add_argument("--artifacts", type=Path, default=PROJECT / "artifacts")
    args = parser.parse_args()
    paths = sorted(path for path in args.data.glob("rda_*.csv") if "excluded" not in path.name)
    data, audit = load_rda(paths)
    metrics = train_initial(data, args.artifacts)
    write_report(metrics, audit, PROJECT / "reports" / "model_report.md")
    (args.artifacts / "data_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"valid_rows": len(data), "groups": [{"group_id": group["group_id"], "status": group["status"], "n_train": group["n_train"], "n_test": group["n_test"]} for group in metrics["groups"]]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
