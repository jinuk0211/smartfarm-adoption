"""Price results must be reproducible before the app displays them as current."""

import hashlib

import pytest

from src.dashboard_extensions import price_result_is_current


@pytest.mark.parametrize("changed", ["input", "code", "output", "manifest"])
def test_stale_price_results_are_hidden(tmp_path, changed):
    relative = "data/processed/kamis_wholesale_monthly_kg.csv"
    paths = [relative, "src/price_forecast.py", "scripts/run_price_forecast.py"]
    outputs = [f"price_forecast_{name}.csv" for name in ["forecast", "holdout_predictions", "validation_predictions"]]
    paths += ["artifacts/" + name for name in outputs]
    hashes = {}
    for name in paths:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(name, encoding="utf-8")
        hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    result = {"input_sha256": hashes[relative],
              "source_sha256": {name: hashes[name] for name in paths[1:3]},
              "output_sha256": {name: hashes["artifacts/" + name] for name in outputs}}
    assert price_result_is_current(tmp_path, result)
    if changed == "manifest":
        result["output_sha256"].pop(outputs[0])
    else:
        target = {"input": relative, "code": paths[1], "output": paths[3]}[changed]
        (tmp_path / target).write_text("changed", encoding="utf-8")
    assert not price_result_is_current(tmp_path, result)
