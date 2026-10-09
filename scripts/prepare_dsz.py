"""Run local DSZ schema preparation with no network access."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.dsz_data import MANAGEMENT_POLICIES, prepare  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--encoding", choices=["utf-8-sig", "cp949"], default="utf-8-sig")
    parser.add_argument("--management-policy", choices=MANAGEMENT_POLICIES, default="single_record_per_cycle")
    args = parser.parse_args()
    manifest = prepare(args.input_dir, args.output_dir, encoding=args.encoding, management_policy=args.management_policy)
    print(json.dumps({key: manifest[key] for key in ["data_kind", "candidate_rows", "target_eligible_rows", "target_assumption"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
