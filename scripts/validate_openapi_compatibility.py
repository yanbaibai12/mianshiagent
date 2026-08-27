#!/usr/bin/env python3
"""Detect breaking changes against the committed OpenAPI operation baseline."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
BASELINE = ROOT / "quality" / "openapi-baseline.json"
APPROVED_REMOVALS = ROOT / "quality" / "openapi-approved-removals.json"
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "options", "head", "trace"}


def _hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _resolve_json_pointer(document: dict[str, Any], reference: str) -> Any:
    if not reference.startswith("#/"):
        return None
    current: Any = document
    for raw_part in reference[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _resolve_local_reference(value: Any, document: dict[str, Any]) -> Any:
    if not isinstance(value, dict):
        return value
    reference = value.get("$ref")
    if isinstance(reference, str) and reference.startswith("#/"):
        return _resolve_json_pointer(document, reference)
    return value


def _hash_schema_contract(value: Any, document: dict[str, Any]) -> str:
    references: dict[str, Any] = {}
    pending: list[str] = []

    def discover(node: Any) -> None:
        if isinstance(node, dict):
            reference = node.get("$ref")
            if isinstance(reference, str) and reference.startswith("#/") and reference not in references:
                pending.append(reference)
            for child in node.values():
                discover(child)
        elif isinstance(node, list):
            for child in node:
                discover(child)

    discover(value)
    while pending:
        reference = pending.pop()
        if reference in references:
            continue
        resolved = _resolve_json_pointer(document, reference)
        references[reference] = resolved
        discover(resolved)

    return _hash({"schema": value, "references": references})


def _content_contract(content: Any, document: dict[str, Any]) -> dict[str, str]:
    if not isinstance(content, dict):
        return {}
    return {
        media_type: _hash_schema_contract(body.get("schema"), document)
        for media_type, body in content.items()
        if isinstance(body, dict)
    }


def _parameter_contracts(
    schema: dict[str, Any], path_item: dict[str, Any], operation: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    contracts: dict[str, dict[str, Any]] = {}
    raw_parameters = [
        *(path_item.get("parameters") or []),
        *(operation.get("parameters") or []),
    ]
    for raw_parameter in raw_parameters:
        parameter = _resolve_local_reference(raw_parameter, schema)
        if not isinstance(parameter, dict):
            continue
        name = parameter.get("name")
        location = parameter.get("in")
        if not isinstance(name, str) or not isinstance(location, str):
            continue
        normalized_name = name.lower() if location == "header" else name
        key = f"{location}:{normalized_name}"
        contracts[key] = {
            "required": True if location == "path" else bool(parameter.get("required", False)),
            "deprecated": bool(parameter.get("deprecated", False)),
            "style": parameter.get("style"),
            "explode": parameter.get("explode"),
            "allow_empty_value": bool(parameter.get("allowEmptyValue", False)),
            "schema_sha256": _hash_schema_contract(parameter.get("schema"), schema),
            "content_sha256": _hash(_content_contract(parameter.get("content"), schema)),
        }
    return dict(sorted(contracts.items()))


def _response_header_contracts(response: Any, schema: dict[str, Any]) -> dict[str, dict[str, str]]:
    response = _resolve_local_reference(response, schema)
    if not isinstance(response, dict):
        return {}
    contracts: dict[str, dict[str, str]] = {}
    for name, raw_header in (response.get("headers") or {}).items():
        header = _resolve_local_reference(raw_header, schema)
        if not isinstance(header, dict):
            continue
        contracts[name.lower()] = {
            "schema_sha256": _hash_schema_contract(header.get("schema"), schema),
            "content_sha256": _hash(_content_contract(header.get("content"), schema)),
        }
    return dict(sorted(contracts.items()))


def _security_contract(schema: dict[str, Any], operation: dict[str, Any]) -> str:
    effective = operation["security"] if "security" in operation else schema.get("security", [])
    normalized_requirements: list[dict[str, list[str]]] = []
    scheme_names: set[str] = set()
    for requirement in effective or []:
        if not isinstance(requirement, dict):
            continue
        normalized: dict[str, list[str]] = {}
        for name, scopes in requirement.items():
            scheme_names.add(name)
            normalized[name] = sorted(scopes) if isinstance(scopes, list) else []
        normalized_requirements.append(dict(sorted(normalized.items())))
    normalized_requirements.sort(key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")))
    available_schemes = schema.get("components", {}).get("securitySchemes", {})
    schemes = {name: available_schemes.get(name) for name in sorted(scheme_names)}
    return _hash({"requirements": normalized_requirements, "schemes": schemes})


def _load_schema() -> dict[str, Any]:
    os.environ.setdefault("APP_ENV", "test")
    os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./openapi_validation.db")
    os.environ.setdefault("AUTO_CREATE_DB", "true")
    sys.path.insert(0, str(BACKEND))
    from app.main import app

    return app.openapi()


def _operation_contracts(schema: dict[str, Any]) -> dict[str, dict[str, Any]]:
    contracts: dict[str, dict[str, Any]] = {}
    for path, path_item in schema.get("paths", {}).items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method.lower() not in HTTP_METHODS or not isinstance(operation, dict):
                continue
            request_body = _resolve_local_reference(operation.get("requestBody") or {}, schema)
            request_body = request_body if isinstance(request_body, dict) else {}
            responses = operation.get("responses") or {}
            response_schemas: dict[str, str] = {}
            response_headers: dict[str, dict[str, dict[str, str]]] = {}
            for code, raw_response in responses.items():
                response = _resolve_local_reference(raw_response, schema)
                response = response if isinstance(response, dict) else {}
                response_schemas[code] = _hash(_content_contract(response.get("content"), schema))
                response_headers[code] = _response_header_contracts(response, schema)
            key = f"{method.upper()} {path}"
            contracts[key] = {
                "operation_id": operation.get("operationId"),
                "parameters": _parameter_contracts(schema, path_item, operation),
                "security_sha256": _security_contract(schema, operation),
                "request_required": bool(request_body.get("required", False)),
                "request_schema_sha256": _hash(_content_contract(request_body.get("content"), schema)),
                "response_codes": sorted(responses),
                "response_schema_sha256": response_schemas,
                "response_headers": response_headers,
            }
    return dict(sorted(contracts.items()))


def _compare_named_contracts(
    *,
    operation: str,
    contract_type: str,
    expected: dict[str, Any],
    actual: dict[str, Any],
) -> list[dict[str, str]]:
    failures: list[dict[str, str]] = []
    for key, expected_contract in expected.items():
        if key not in actual:
            failures.append({"operation": operation, "reason": f"{contract_type}_removed:{key}"})
        elif actual[key] != expected_contract:
            failures.append({"operation": operation, "reason": f"{contract_type}_changed:{key}"})
    return failures


def _compare(baseline: dict[str, Any], current: dict[str, dict[str, Any]]) -> list[dict[str, str]]:
    failures: list[dict[str, str]] = []
    expected = baseline.get("operations", {})
    for key, contract in expected.items():
        actual = current.get(key)
        if actual is None:
            failures.append({"operation": key, "reason": "operation_removed"})
            continue
        for field in (
            "operation_id",
            "security_sha256",
            "request_required",
            "request_schema_sha256",
        ):
            if actual.get(field) != contract.get(field):
                failures.append({"operation": key, "reason": f"{field}_changed"})

        expected_parameters = contract.get("parameters", {})
        actual_parameters = actual.get("parameters", {})
        failures.extend(
            _compare_named_contracts(
                operation=key,
                contract_type="parameter",
                expected=expected_parameters,
                actual=actual_parameters,
            )
        )
        for parameter_key, parameter in actual_parameters.items():
            if parameter_key not in expected_parameters and parameter.get("required"):
                failures.append(
                    {
                        "operation": key,
                        "reason": f"required_parameter_added:{parameter_key}",
                    }
                )

        missing_codes = sorted(set(contract.get("response_codes", [])) - set(actual.get("response_codes", [])))
        if missing_codes:
            failures.append(
                {
                    "operation": key,
                    "reason": f"response_codes_removed:{','.join(missing_codes)}",
                }
            )
        for code, digest in contract.get("response_schema_sha256", {}).items():
            if code in actual.get("response_schema_sha256", {}) and actual["response_schema_sha256"][code] != digest:
                failures.append({"operation": key, "reason": f"response_schema_changed:{code}"})
        for code, expected_headers in contract.get("response_headers", {}).items():
            if code not in actual.get("response_headers", {}):
                continue
            failures.extend(
                _compare_named_contracts(
                    operation=key,
                    contract_type=f"response_header:{code}",
                    expected=expected_headers,
                    actual=actual["response_headers"][code],
                )
            )
    return failures


def _load_approved_removals(path: Path) -> tuple[dict[str, Any], list[str]]:
    if not path.exists():
        return {}, []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {}, [f"approved_removals_unreadable:{exc}"]
    if not isinstance(data, dict):
        return {}, ["approved_removals_must_be_an_object"]
    return data, []


def _validate_approved_removals(
    data: dict[str, Any],
    *,
    baseline: dict[str, Any],
    current: dict[str, dict[str, Any]],
    root: Path,
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    if not data:
        return {}, []

    errors: list[str] = []
    approvals: dict[str, dict[str, Any]] = {}
    if data.get("schema_version") != "1.0":
        errors.append("approved_removals.schema_version_must_be_1.0")
    for field in ("phase", "owner", "adr"):
        value = data.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"approved_removals.{field}_must_be_non_empty")

    adr_value = data.get("adr")
    if isinstance(adr_value, str) and adr_value.strip():
        adr_path = Path(adr_value)
        if adr_path.is_absolute():
            errors.append("approved_removals.adr_must_be_repository_relative")
        else:
            resolved_root = root.resolve()
            resolved_adr = (root / adr_path).resolve()
            try:
                resolved_adr.relative_to(resolved_root)
            except ValueError:
                errors.append("approved_removals.adr_must_stay_within_repository")
            else:
                if not resolved_adr.is_file():
                    errors.append("approved_removals.adr_file_missing")

    raw_operations = data.get("operations")
    if not isinstance(raw_operations, list) or not raw_operations:
        errors.append("approved_removals.operations_must_be_non_empty")
        return approvals, errors

    baseline_operations = baseline.get("operations", {})
    for index, item in enumerate(raw_operations):
        prefix = f"approved_removals.operations[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix}_must_be_an_object")
            continue
        method = item.get("method")
        path = item.get("path")
        owner = item.get("owner") or data.get("owner")
        reason = item.get("reason")
        replacement = item.get("replacement")
        if not isinstance(method, str) or method.lower() not in HTTP_METHODS:
            errors.append(f"{prefix}.method_invalid")
            continue
        if not isinstance(path, str) or not path.startswith("/"):
            errors.append(f"{prefix}.path_invalid")
            continue
        operation = f"{method.upper()} {path}"
        if operation in approvals:
            errors.append(f"{prefix}.duplicate:{operation}")
            continue
        if operation not in baseline_operations:
            errors.append(f"{prefix}.not_in_baseline:{operation}")
            continue
        if operation in current:
            errors.append(f"{prefix}.not_removed:{operation}")
            continue
        if not isinstance(owner, str) or not owner.strip():
            errors.append(f"{prefix}.owner_must_be_non_empty")
            continue
        if not isinstance(reason, str) or len(reason.strip()) < 12:
            errors.append(f"{prefix}.reason_too_short")
            continue
        if replacement is not None and (not isinstance(replacement, str) or not replacement.strip()):
            errors.append(f"{prefix}.replacement_must_be_null_or_non_empty")
            continue
        approvals[operation] = {
            "operation": operation,
            "owner": owner.strip(),
            "reason": reason.strip(),
            "replacement": replacement.strip() if isinstance(replacement, str) else None,
            "phase": str(data.get("phase") or "").strip(),
            "adr": str(data.get("adr") or "").strip(),
        }
    return approvals, errors


def _partition_approved_removals(
    failures: list[dict[str, str]], approvals: dict[str, dict[str, Any]]
) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    blocking: list[dict[str, str]] = []
    approved: list[dict[str, Any]] = []
    for failure in failures:
        operation = failure.get("operation", "")
        if failure.get("reason") == "operation_removed" and operation in approvals:
            approved.append(approvals[operation])
        else:
            blocking.append(failure)
    return blocking, approved


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help="Write the current contract as the reviewed baseline",
    )
    args = parser.parse_args()
    schema = _load_schema()
    operations = _operation_contracts(schema)
    if args.write_baseline:
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": "1.0",
            "baseline_date": datetime.now(timezone.utc).date().isoformat(),
            "openapi_version": schema.get("openapi"),
            "title": schema.get("info", {}).get("title"),
            "operation_count": len(operations),
            "operations": operations,
        }
        BASELINE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(
            json.dumps(
                {
                    "status": "written",
                    "path": str(BASELINE),
                    "operation_count": len(operations),
                }
            )
        )
        return 0
    if not BASELINE.exists():
        print(
            json.dumps(
                {
                    "status": "failed",
                    "reason": "baseline_missing",
                    "path": str(BASELINE),
                }
            )
        )
        return 1
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    failures = _compare(baseline, operations)
    approval_data, approval_errors = _load_approved_removals(APPROVED_REMOVALS)
    approvals, validation_errors = _validate_approved_removals(
        approval_data,
        baseline=baseline,
        current=operations,
        root=ROOT,
    )
    approval_errors.extend(validation_errors)
    blocking_failures, approved_removals = _partition_approved_removals(failures, approvals)
    passed = not blocking_failures and not approval_errors
    payload = {
        "schema_version": "1.0",
        "status": "passed" if passed else "failed",
        "baseline_operation_count": baseline.get("operation_count"),
        "current_operation_count": len(operations),
        "approved_removals": approved_removals,
        "approval_errors": approval_errors,
        "breaking_changes": blocking_failures,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
