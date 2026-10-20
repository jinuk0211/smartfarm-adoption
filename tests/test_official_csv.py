"""Synthetic-only checks for the dictionary's named, unquoted CSV exports."""

import csv
from copy import deepcopy
import pandas as pd
import pytest

from src import dsz_data as dsz


TABLE_IDS = [f"DZ_{number:03}" for number in range(1, 8)]


def selected_schema(table_id):
    schema = deepcopy(dsz.load_schema())
    schema["tables"] = {table_id: schema["tables"][table_id]}
    schema["tables"][table_id]["required"] = True
    return schema


def write_synthetic(path, table, delimiter, *, quoted=False, header=None):
    columns = header or [column["name"] for column in table["columns"]]
    values = {name: "" for name in columns}
    values.update(FCLT_ID="00017", STR_USERID='"literal quote')
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream, delimiter=delimiter,
                            quoting=csv.QUOTE_MINIMAL if quoted else csv.QUOTE_NONE,
                            quotechar='"' if quoted else None)
        writer.writerow(columns)
        writer.writerow([values[name] for name in columns])


@pytest.mark.parametrize("table_id", TABLE_IDS)
def test_exact_official_export_names_and_formats(tmp_path, table_id):
    schema = selected_schema(table_id)
    table = schema["tables"][table_id]
    base = "M_DZ_SFARMMANAGEINQUIRY" if table_id == "DZ_004" else table["filename"]
    assert table["export_filename"] == f"{table['label']}({base}).csv"
    assert table["export_delimiter"] == ("," if table_id == "DZ_006" else "|")
    assert table["export_quoting"] is False
    path = tmp_path / table["export_filename"]
    write_synthetic(path, table, table["export_delimiter"])

    tables, sources = dsz.load_tables(tmp_path, schema)

    assert tables[table_id].loc[0, "FCLT_ID"] == "00017"
    assert tables[table_id].loc[0, "STR_USERID"] == '"literal quote'
    assert tables[table_id].loc[0, "_source_row"] == 2
    assert sources[0]["sha256"] == dsz.sha256(path)
    assert sources[0]["delimiter"] == table["export_delimiter"]
    assert sources[0]["quoting"] is False
    assert sources[0]["encoding"] == "utf-8-sig"


@pytest.mark.parametrize("table_id", TABLE_IDS)
@pytest.mark.parametrize("delimiter", [",", "|"])
def test_legacy_dz_alias_accepts_exact_comma_or_pipe_header(tmp_path, table_id, delimiter):
    schema = selected_schema(table_id)
    table = schema["tables"][table_id]
    write_synthetic(tmp_path / f"{table_id}.csv", table, delimiter, quoted=delimiter == ",")

    tables, sources = dsz.load_tables(tmp_path, schema)

    assert tables[table_id].loc[0, "FCLT_ID"] == "00017"
    assert tables[table_id].loc[0, "STR_USERID"] == '"literal quote'
    assert sources[0]["delimiter"] == delimiter


@pytest.mark.parametrize("basename", ["M_DZ_SFARMMANAGEMENT", "M_DZ_SFARMMANAGEINQUIRY"])
@pytest.mark.parametrize("delimiter", [",", "|"])
def test_both_management_table_aliases_work(tmp_path, basename, delimiter):
    schema = selected_schema("DZ_004")
    write_synthetic(tmp_path / f"{basename}.csv", schema["tables"]["DZ_004"], delimiter,
                    quoted=delimiter == ",")
    tables, _ = dsz.load_tables(tmp_path, schema)
    assert tables["DZ_004"].loc[0, "FCLT_ID"] == "00017"


@pytest.mark.parametrize("alias", ["DZ_004", "M_DZ_SFARMMANAGEMENT", "M_DZ_SFARMMANAGEINQUIRY"])
def test_duplicate_file_aliases_are_rejected(tmp_path, alias):
    schema = selected_schema("DZ_004")
    table = schema["tables"]["DZ_004"]
    write_synthetic(tmp_path / table["export_filename"], table, "|")
    write_synthetic(tmp_path / f"{alias}.csv", table, ",", quoted=True)
    with pytest.raises(ValueError, match="More than one file for DZ_004"):
        dsz.load_tables(tmp_path, schema)


@pytest.mark.parametrize("malformation", ["missing", "duplicate", "renamed", "reserved", "semicolon"])
def test_malformed_headers_fail_without_guessing(tmp_path, malformation):
    schema = selected_schema("DZ_002")
    table = schema["tables"]["DZ_002"]
    header = [column["name"] for column in table["columns"]]
    if malformation == "missing":
        header.remove("FCLT_ID")
    elif malformation == "duplicate":
        header.append("FCLT_ID")
    elif malformation == "renamed":
        header[header.index("FCLT_ID")] = "facility_id"
    elif malformation == "reserved":
        header.append("_source_row")
    delimiter = ";" if malformation == "semicolon" else ","
    write_synthetic(tmp_path / "DZ_002.csv", table, delimiter, quoted=True, header=header)
    with pytest.raises(ValueError, match="exact named columns"):
        dsz.load_tables(tmp_path, schema)


def test_official_name_requires_declared_separator(tmp_path):
    schema = selected_schema("DZ_002")
    table = schema["tables"]["DZ_002"]
    write_synthetic(tmp_path / table["export_filename"], table, ",", quoted=True)
    with pytest.raises(ValueError, match="exact named columns"):
        dsz.load_tables(tmp_path, schema)


def test_additional_columns_are_preserved_and_audited(tmp_path):
    schema = selected_schema("DZ_002")
    table = schema["tables"]["DZ_002"]
    header = [column["name"] for column in table["columns"]] + ["EXTRA_NOTE"]
    write_synthetic(tmp_path / "DZ_002.csv", table, "|", header=header)
    tables, sources = dsz.load_tables(tmp_path, schema)
    assert "EXTRA_NOTE" in tables["DZ_002"].columns
    assert sources[0]["extra_columns"] == ["EXTRA_NOTE"]


def test_extra_csv_fields_do_not_silently_shift_facility_id(tmp_path):
    schema = selected_schema("DZ_002")
    table = schema["tables"]["DZ_002"]
    path = tmp_path / table["export_filename"]
    write_synthetic(path, table, "|")
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    path.write_text(lines[0] + "\n" + "EXTRA|" + lines[1] + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="more fields"):
        dsz.load_tables(tmp_path, schema)


def test_existing_synthetic_comma_fixture_is_unchanged():
    fixture_dir = dsz.ROOT / "data/examples/dsz_inseason/input"
    tables, sources = dsz.load_tables(fixture_dir, dsz.load_schema())
    expected = pd.read_csv(fixture_dir / "DZ_002.csv", dtype=str, keep_default_na=False)
    pd.testing.assert_frame_equal(tables["DZ_002"][expected.columns], expected)
    assert all(source["delimiter"] == "," for source in sources)
