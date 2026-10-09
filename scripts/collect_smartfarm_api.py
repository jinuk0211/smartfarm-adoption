"""Collect authenticated Smartfarm Korea crop-year records without aggregating them.

Only SMARTFARM_API_KEY supplies the credential. No examples from API documentation
are read as data. Confirmed no-data responses are saved without business records.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote
from urllib.request import HTTPRedirectHandler, Request, build_opener


ROOT = Path(__file__).resolve().parents[1]
BASE_URL = "https://www.smartfarmkorea.net/Agree_WS/webservices/DataMartYearRestService"
OPERATIONS = {
    "getFcltyInfoDataList": (),
    "getFcltyDateInfoData": ("fcltyId", "fcltyYear"),
    "getMngtOutputDataList": ("fcltyId", "crpsnSn", "fixPlntngDe", "crpsnEndDe"),
    "getMngtCostDataList": ("fcltyId", "crpsnSn", "fixPlntngDe", "crpsnEndDe"),
    "getEnvInfoDataList": ("fcltyId", "crpsnSn", "itemCode", "fixPlntngDe", "crpsnEndDe"),
    "getExaminInfoDataList": ("fcltyId", "crpsnSn", "fixPlntngDe", "crpsnEndDe"),
}
NO_DATA_FIELDS = {
    "getMngtOutputDataList": (
        {"fcltyId", "opShipDe", "opShipPlc", "opNote"},
        {"crpsnSn", "opAllShip", "opLvAa", "opLvA", "opLvB", "opLvC",
         "opLvAaWon", "opLvAWon", "opLvBWon", "opLvCWon", "opIncome", "opUnpsRate"},
    ),
    "getMngtCostDataList": (
        {"fcltyId", "ctPayDe"},
        {"crpsnSn", "ctOpcWkCost", "ctFmwWkTime", "fmwWkCost", "ctFmwWkPpl"},
    ),
}


class CollectionError(Exception):
    """A fixed, credential-free diagnostic suitable for terminal output."""


class RequestLimitError(CollectionError):
    """The explicit network request budget was exhausted."""


class RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise CollectionError("Redirect rejected; verify the official HTTPS endpoint.")


def sanitize(value, key: str):
    """Redact raw and URL-encoded credentials, including echoed response URLs."""
    variants = {key, unquote(key), quote(key, safe=""), quote(quote(key, safe=""), safe="")}
    variants.discard("")
    pattern = re.compile("|".join(re.escape(item) for item in sorted(variants, key=len, reverse=True)), re.I)
    if isinstance(value, str):
        return pattern.sub("[REDACTED]", value)
    if isinstance(value, list):
        return [sanitize(item, key) for item in value]
    if isinstance(value, dict):
        return {sanitize(str(name), key): sanitize(item, key) for name, item in value.items()}
    return value


def extract_records(payload) -> list[dict]:
    """Accept the documented array and common JSON wrappers; reject ambiguity."""
    if isinstance(payload, list):
        result = []
        for item in payload:
            if not isinstance(item, dict):
                raise CollectionError("Response contains a non-object record.")
            result.extend(extract_records(item))
        return result
    if not isinstance(payload, dict):
        if payload is None:
            return []
        raise CollectionError("Unsupported response shape.")
    for field in ("statusCode", "resultCode"):
        if field in payload and payload[field] not in (None, "", "00", "0", 0):
            raise CollectionError("API returned a non-success status; inspect the redacted response.")
    if "fcltyId" in payload:
        return [payload]
    wrappers = [name for name in ("response", "body", "items", "item", "data", "rows", "result", "records")
                if name in payload and isinstance(payload[name], (list, dict, type(None)))]
    if len(wrappers) == 1:
        return extract_records(payload[wrappers[0]])
    if len(wrappers) > 1:
        raise CollectionError("Ambiguous response wrappers; inspect the redacted response.")
    if not payload or set(payload) <= {"statusCode", "statusMessage", "resultCode", "resultMsg"}:
        return []
    # A header contains only status information; body carries the records.
    if "header" in payload and "body" not in payload:
        return extract_records(payload["header"])
    raise CollectionError("Unrecognized record schema; inspect the redacted response.")


def validate_statuses(payload) -> None:
    """Check status fields in headers as well as every row before unwrapping."""
    if isinstance(payload, dict):
        for name, value in payload.items():
            if name in {"statusCode", "resultCode"} and value not in (None, "", "00", "0", 0):
                raise CollectionError("API returned a non-success status; inspect the redacted response.")
            validate_statuses(value)
    elif isinstance(payload, list):
        for item in payload:
            validate_statuses(item)


def response_records(payload, operation: str) -> tuple[list[dict], bool]:
    """Recognize only the two null/zero no-data schemas observed in real pilots."""
    if operation in NO_DATA_FIELDS and isinstance(payload, list) and len(payload) == 1:
        row = payload[0]
        null_fields, zero_fields = NO_DATA_FIELDS[operation]
        if (isinstance(row, dict)
                and set(row) == null_fields | zero_fields | {"statusCode", "statusMessage"}
                and row["statusCode"] == "03" and row["statusMessage"] == "NODATA_ERROR"
                and all(row[name] is None for name in null_fields)
                and all(type(row[name]) in (int, float) and row[name] == 0 for name in zero_fields)):
            return [], True
    validate_statuses(payload)
    return extract_records(payload), False


class APIClient:
    def __init__(self, key: str, run_dir: Path, max_requests: int = 30,
                 max_response_bytes: int = 16 * 1024 * 1024, opener=None,
                 request_interval_seconds: float = 1.0, resume_from: Path | None = None):
        if not key:
            raise CollectionError("SMARTFARM_API_KEY is required.")
        self.key = key
        self.run_dir = run_dir
        self.max_requests = max_requests
        self.max_response_bytes = max_response_bytes
        self.opener = opener if opener is not None else build_opener(RejectRedirects())
        self.request_interval_seconds = request_interval_seconds
        self.last_request_start = None
        self.network_requests = 0
        self.resume_from = resume_from.resolve() if resume_from is not None else None
        self.resume_index = {}
        if self.resume_from is not None:
            try:
                previous = json.loads((self.resume_from / "manifest.json").read_text(encoding="utf-8"))
                if previous.get("endpoint_base") != BASE_URL:
                    raise ValueError
                for entry in previous["requests"]:
                    if entry.get("status") == "saved":
                        signature = self.request_signature(entry["source_operation"], entry["parameters"])
                        self.resume_index[signature] = entry
            except (OSError, ValueError, KeyError, TypeError):
                raise CollectionError("Cannot read the previous collection manifest.") from None
        self.manifest = {"status": "in_progress", "started_at_utc": utc_now(), "requests": [],
                         "endpoint_base": BASE_URL,
                         "request_interval_seconds": request_interval_seconds,
                         "shipment_aggregation": "not_performed_cumulative_definition_unverified",
                         "training_eligible": False, "source_kind": "authenticated_api_records_pending_audit"}
        run_dir.mkdir(parents=True, exist_ok=False)
        self.save_manifest()

    def save_manifest(self) -> None:
        self.manifest["network_request_count"] = self.network_requests
        self.manifest["reused_response_count"] = sum(entry.get("transport") == "verified_cache" for entry in self.manifest["requests"])
        path = self.run_dir / "manifest.json"
        path.write_text(json.dumps(sanitize(self.manifest, self.key), ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def request_signature(operation: str, params: dict) -> str:
        return json.dumps([operation, params], sort_keys=True, ensure_ascii=False, separators=(",", ":"))

    def cached_payload(self, operation: str, params: dict):
        """Use only an exact key-free request with both saved-file hashes intact."""
        entry = self.resume_index.get(self.request_signature(operation, params))
        if entry is None:
            return None
        try:
            contents = {}
            for kind in ("response", "records"):
                filename = entry[f"{kind}_file"]
                path = (self.resume_from / filename).resolve()
                if path.parent != self.resume_from or Path(filename).name != filename:
                    raise ValueError
                contents[kind] = path.read_bytes()
                if hashlib.sha256(contents[kind]).hexdigest() != entry[f"{kind}_sha256"]:
                    raise ValueError
            payload = json.loads(contents["response"].decode("utf-8"))
            records, _ = response_records(payload, operation)
            stored_records = [json.loads(line) for line in contents["records"].decode("utf-8").splitlines()]
            if records != stored_records:
                raise ValueError
            return payload
        except (OSError, ValueError, KeyError, TypeError, UnicodeError):
            raise CollectionError("Previous response integrity check failed; cache was not used.") from None

    def fetch(self, operation: str, **params) -> list[dict]:
        if operation not in OPERATIONS or set(params) != set(OPERATIONS[operation]):
            raise CollectionError("Invalid operation or request parameters.")
        cached = self.cached_payload(operation, params)
        if cached is None and self.network_requests >= self.max_requests:
            raise RequestLimitError("Request limit reached; increase --max-requests explicitly.")
        values = [str(params[name]) for name in OPERATIONS[operation]]
        if any(not value or value == "None" for value in values):
            raise CollectionError("Missing required request parameter.")
        url = "/".join([BASE_URL, operation, quote(self.key, safe=""), *(quote(value, safe="") for value in values)])
        sequence = len(self.manifest["requests"]) + 1
        stem = f"{sequence:04d}_{operation}"
        entry = {"source_operation": operation, "parameters": sanitize(params, self.key),
                 "retrieved_at_utc": utc_now(), "status": "requested", "record_count": None,
                 "transport": "verified_cache" if cached is not None else "https"}
        self.manifest["requests"].append(entry)
        self.save_manifest()
        try:
            if cached is not None:
                previous = self.resume_index[self.request_signature(operation, params)]
                entry.update({"original_retrieved_at_utc": previous.get("original_retrieved_at_utc", previous.get("retrieved_at_utc")),
                              "cache_response_sha256": previous["response_sha256"]})
                payload = sanitize(cached, self.key)
            else:
                if self.last_request_start is not None:
                    remaining = self.request_interval_seconds - (time.monotonic() - self.last_request_start)
                    if remaining > 0:
                        time.sleep(remaining)
                self.last_request_start = time.monotonic()
                self.network_requests += 1
                with self.opener.open(Request(url, headers={"Accept": "application/json"}), timeout=30) as response:
                    entry["http_status"] = response.status
                    body = response.read(self.max_response_bytes + 1)
                if len(body) > self.max_response_bytes:
                    raise CollectionError("Response byte limit exceeded; request a smaller time range.")
                payload = sanitize(json.loads(body.decode("utf-8-sig")), self.key)
            saved = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            response_path = self.run_dir / f"{stem}.response.json"
            response_path.write_bytes(saved)
            entry.update({"response_file": response_path.name, "response_bytes": len(saved),
                          "response_sha256": hashlib.sha256(saved).hexdigest(),
                          "response_storage": "JSON_reserialized_with_credential_redaction"})
            records, no_data = response_records(payload, operation)
            entry["no_data"] = no_data
            if no_data:
                entry.update({"api_status_code": "03", "api_status_message": "NODATA_ERROR"})
            rows = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in records).encode("utf-8")
            records_path = self.run_dir / f"{stem}.records.jsonl"
            records_path.write_bytes(rows)
            entry.update({"records_file": records_path.name, "records_sha256": hashlib.sha256(rows).hexdigest(),
                          "record_count": len(records), "status": "saved"})
        except HTTPError as error:
            entry.update({"status": "failed", "http_status": error.code})
            raise CollectionError(f"HTTP {error.code}; verify approval and endpoint availability.") from None
        except (URLError, TimeoutError, OSError):
            entry["status"] = "failed"
            raise CollectionError("Transport or file error; no credential-bearing details were logged.") from None
        except (UnicodeError, json.JSONDecodeError):
            entry["status"] = "failed"
            raise CollectionError("Response is not UTF-8 JSON; no response body was logged.") from None
        except CollectionError:
            entry["status"] = "failed"
            raise
        finally:
            self.save_manifest()
        return records


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_date(value: str) -> date:
    return date.fromisoformat(value)


def collect(client: APIClient, args) -> None:
    farms = client.fetch("getFcltyInfoDataList")
    crop_counts = {}
    for farm in farms:
        name = str(farm.get("itemCodeNm", ""))
        crop_counts[name] = crop_counts.get(name, 0) + 1
    client.manifest["catalog"] = {
        "record_count": len(farms), "facility_count": len({str(f.get("fcltyId", "")) for f in farms if f.get("fcltyId")}),
        "facility_year_count": len({(str(f.get("fcltyId", "")), str(f.get("fcltyYear", ""))) for f in farms if f.get("fcltyId")}),
        "crop_record_counts": crop_counts,
    }
    client.manifest["selection"] = {"facility": args.facility, "year": args.year, "crop": args.crop,
                                    "start": str(args.start) if args.start else None,
                                    "end": str(args.end) if args.end else None,
                                    "include_timeseries": args.include_timeseries}
    if args.list_only:
        client.manifest.update({"status": "catalog_only", "completed_at_utc": utc_now()})
        client.save_manifest()
        return
    pairs, seen = [], set()
    skips = client.manifest.setdefault("skipped_cycles", [])
    for farm in farms:
        facility, year = str(farm.get("fcltyId", "")), str(farm.get("fcltyYear", ""))
        if args.facility and facility not in args.facility:
            continue
        if args.year and year not in args.year:
            continue
        if args.crop and str(farm.get("itemCodeNm", "")) not in args.crop:
            continue
        if not facility or not re.fullmatch(r"\d{4}", year):
            skips.append({"reason": "invalid_catalog_facility_or_year"})
            continue
        if (facility, year) not in seen:
            pairs.append((facility, year))
            seen.add((facility, year))
    matching_facilities = list(dict.fromkeys(facility for facility, _ in pairs))
    selected_facilities = matching_facilities[:args.max_farms]
    selected_pairs = [(facility, year) for facility, year in pairs if facility in selected_facilities]
    coverage = {"matching_facility_count": len(matching_facilities), "matching_facility_year_count": len(pairs),
                "selected_facility_count": len(selected_facilities), "selected_facility_year_count": len(selected_pairs),
                "facilities_omitted_by_limit": len(matching_facilities) - len(selected_facilities),
                "unvisited_facility_year_count": 0, "cycles_omitted_by_limit": 0,
                "collected_cycle_count": 0, "limit_reasons": []}
    client.manifest["coverage"] = coverage
    seen_cycles, collected_cycles = set(), 0
    for pair_index, (facility, year) in enumerate(selected_pairs):
        if collected_cycles >= args.max_cycles:
            coverage["unvisited_facility_year_count"] = len(selected_pairs) - pair_index
            break
        cycles = client.fetch("getFcltyDateInfoData", fcltyId=facility, fcltyYear=year)
        for cycle in cycles:
            cycle_id = cycle.get("crpsnSn")
            identity = (facility, str(cycle_id))
            if identity in seen_cycles:
                continue
            if args.crop and str(cycle.get("itemCodeNm", "")) not in args.crop:
                continue
            seen_cycles.add(identity)
            try:
                start = parse_date(cycle.get("fixplntngDe", cycle.get("fixPlntngDe", "")))
                end = parse_date(cycle.get("crpsnEndDe", ""))
                if str(cycle.get("fcltyId", "")) != facility or cycle_id is None or end < start:
                    raise ValueError
            except (ValueError, TypeError):
                skips.append({"fcltyId": facility, "crpsnSn": cycle_id, "reason": "invalid_identity_or_crop_dates"})
                continue
            start = max(start, args.start) if args.start else start
            end = min(end, args.end) if args.end else end
            if start > end:
                skips.append({"fcltyId": facility, "crpsnSn": cycle_id, "reason": "no_date_overlap"})
                continue
            if collected_cycles >= args.max_cycles:
                coverage["cycles_omitted_by_limit"] += 1
                continue
            params = {"fcltyId": facility, "crpsnSn": cycle_id,
                      "fixPlntngDe": start.strftime("%Y%m%d"), "crpsnEndDe": end.strftime("%Y%m%d")}
            client.fetch("getMngtOutputDataList", **params)
            client.fetch("getMngtCostDataList", **params)
            if args.include_timeseries:
                item_code = cycle.get("itemCode")
                if item_code is not None and str(item_code):
                    client.fetch("getEnvInfoDataList", **params, itemCode=item_code)
                else:
                    skips.append({"fcltyId": facility, "crpsnSn": cycle_id, "reason": "missing_environment_item_code"})
                client.fetch("getExaminInfoDataList", **params)
            collected_cycles += 1
            coverage["collected_cycle_count"] = collected_cycles
    if coverage["facilities_omitted_by_limit"]:
        coverage["limit_reasons"].append("max_farms")
    if coverage["unvisited_facility_year_count"] or coverage["cycles_omitted_by_limit"]:
        coverage["limit_reasons"].append("max_cycles")
    status = "truncated" if coverage["limit_reasons"] else "completed_with_skips" if skips else "completed"
    if not pairs:
        status = "no_matching_catalog_records"
    client.manifest.update({"collected_cycle_count": collected_cycles, "selected_facility_count": len(selected_facilities),
                            "status": status, "completed_at_utc": utc_now()})
    client.save_manifest()


def positive(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def nonnegative_seconds(value: str) -> float:
    number = float(value)
    if not 0 <= number <= 60:
        raise argparse.ArgumentTypeError("must be between 0 and 60 seconds")
    return number


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--facility", action="append", help="facility ID; repeat to select more")
    parser.add_argument("--year", action="append", help="crop management year; repeat to select more")
    parser.add_argument("--crop", action="append", help="exact official itemCodeNm; repeat to select more crops")
    parser.add_argument("--list-only", action="store_true", help="save only the complete facility catalog, without follow-up requests")
    parser.add_argument("--resume-from", type=Path, help="previous run directory; reuse only exact requests with verified response/record hashes")
    parser.add_argument("--request-interval-seconds", type=nonnegative_seconds, default=1.0,
                        help="minimum interval between network request starts; not an official quota guarantee")
    parser.add_argument("--start", type=parse_date, help="inclusive ISO date YYYY-MM-DD")
    parser.add_argument("--end", type=parse_date, help="inclusive ISO date YYYY-MM-DD")
    parser.add_argument("--max-farms", type=positive, default=3)
    parser.add_argument("--max-cycles", type=positive, default=3, help="total crop cycles, not per farm")
    parser.add_argument("--max-requests", type=positive, default=30)
    parser.add_argument("--max-response-mb", type=positive, default=16)
    parser.add_argument("--include-timeseries", action="store_true", help="also collect environment and growth")
    parser.add_argument("--max-timeseries-days", type=positive, default=31)
    parser.add_argument("--output-root", type=Path, default=ROOT / "data/raw/smartfarm_api")
    args = parser.parse_args(argv)
    if args.start and args.end and args.start > args.end:
        parser.error("--start must not be after --end")
    if args.include_timeseries:
        if not args.start or not args.end:
            parser.error("--include-timeseries requires --start and --end")
        if (args.end - args.start + timedelta(days=1)).days > args.max_timeseries_days:
            parser.error("timeseries range exceeds --max-timeseries-days")
    key = os.environ.get("SMARTFARM_API_KEY", "").strip()
    if not key or key in {"YOUR_APPROVED_KEY", "SERVICE_KEY"}:
        print("SMARTFARM_API_KEY is required; no API request was made.", file=sys.stderr)
        return 2
    run_name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ_") + uuid.uuid4().hex[:8]
    client = None
    try:
        client = APIClient(key, args.output_root / run_name, args.max_requests, args.max_response_mb * 1024 * 1024,
                           request_interval_seconds=args.request_interval_seconds, resume_from=args.resume_from)
        collect(client, args)
    except RequestLimitError as error:
        client.manifest.update({"status": "truncated", "limit_reasons": ["max_requests"],
                                "error": str(error), "completed_at_utc": utc_now()})
        client.save_manifest()
        print(str(error), file=sys.stderr)
        return 3
    except CollectionError as error:
        if client is not None:
            client.manifest.update({"status": "failed", "error": str(error), "completed_at_utc": utc_now()})
            client.save_manifest()
        print(sanitize(str(error), key), file=sys.stderr)
        return 1
    except Exception:
        # This CLI boundary must never emit a traceback containing a keyed URL.
        if client is not None:
            client.manifest.update({"status": "failed", "error": "Unexpected collection failure",
                                    "completed_at_utc": utc_now()})
            try:
                client.save_manifest()
            except OSError:
                pass
        print("Collection failed; raw exception details were suppressed to protect credentials.", file=sys.stderr)
        return 1
    print(f"Status: {client.manifest['status']}; saved {len(client.manifest['requests'])} responses; "
          f"network requests: {client.network_requests}; no shipment or cost aggregation performed.")
    return 3 if client.manifest["status"] in {"truncated", "completed_with_skips", "no_matching_catalog_records"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
