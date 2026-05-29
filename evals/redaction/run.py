from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import os
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
GUARDRAILS_ROOT = ROOT / "guardrails"
if str(GUARDRAILS_ROOT) not in sys.path:
    sys.path.insert(0, str(GUARDRAILS_ROOT))

from fastapi.testclient import TestClient  

from app.main import app as guardrails_app  
from app.redaction import RedactionFilter as GuardrailsRedactionFilter  
from app.tracing import is_safe_span_attribute as guardrails_safe_attr  

GATE_NAME = "redaction"
FIXTURE_DIR = ROOT / "evals" / "redaction" / "fixtures"
THRESHOLDS_PATH = ROOT / "eval_thresholds.yaml"
SERVICE_TOKEN = "redaction-eval-token"


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {name} from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


backend_redaction = _load_module(
    "redaction_eval_backend_redaction",
    ROOT / "backend" / "app" / "core" / "redaction.py",
)
modelserver_redaction = _load_module(
    "redaction_eval_modelserver_redaction",
    ROOT / "modelserver" / "app" / "redaction.py",
)
modelserver_tracing = _load_module(
    "redaction_eval_modelserver_tracing",
    ROOT / "modelserver" / "app" / "tracing.py",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Owner C redaction leak gate.")
    parser.add_argument("--output", type=Path, help="Optional JSONL result path for CI.")
    return parser.parse_args()


def load_required_pass_rate() -> float:
    section: str | None = None
    for raw_line in THRESHOLDS_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if not raw_line.startswith((" ", "\t")) and line.endswith(":"):
            section = line[:-1].strip()
            continue
        if section == "redaction":
            key, separator, value = line.strip().partition(":")
            if separator and key.strip() == "required_pass_rate":
                return float(value.strip())
    raise KeyError(f"missing redaction.required_pass_rate in {THRESHOLDS_PATH}")


def load_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for path in sorted(FIXTURE_DIR.glob("*.jsonl")):
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if line.strip():
                    case = json.loads(line)
                    case["_fixture"] = f"{path.name}:{line_number}"
                    cases.append(case)
    if not cases:
        raise ValueError(f"no fixtures found under {FIXTURE_DIR}")
    return cases


def _raw_values(case: dict[str, Any]) -> list[str]:
    values = [value for value in case.get("must_not_appear", []) if value]
    return [str(value) for value in values]


def _assert_no_raw(surface: str, text: str, raw_values: list[str]) -> list[str]:
    return [surface for raw in raw_values if raw in text]


def _check_redaction_module(
    surface: str,
    module: ModuleType,
    case: dict[str, Any],
) -> list[str]:
    result = module.redact(case["text"])
    failures = _assert_no_raw(surface, result.text, _raw_values(case))
    for expected_type in case.get("expected_redaction_types", []):
        if result.counts.get(expected_type, 0) < 1:
            failures.append(f"{surface}:missing_type:{expected_type}")
    if not case.get("expected_redaction_types") and result.total:
        failures.append(f"{surface}:benign_over_redacted")
    return failures


def _check_log_filter(surface: str, filter_class: type[logging.Filter], case: dict[str, Any]) -> list[str]:
    record = logging.LogRecord(
        name=f"albert.eval.{surface}",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=case["text"],
        args=(),
        exc_info=None,
    )
    filter_class().filter(record)
    return _assert_no_raw(f"{surface}:log", record.getMessage(), _raw_values(case))


def _check_guardrails_response(client: TestClient, case: dict[str, Any]) -> list[str]:
    response = client.post(
        "/guardrails/output",
        headers={"Authorization": f"Bearer {SERVICE_TOKEN}"},
        json={"text": case["text"]},
    )
    if response.status_code != 200:
        return [f"guardrails_response:status:{response.status_code}"]
    body = response.json()
    failures = _assert_no_raw("guardrails_response", response.text, _raw_values(case))
    if case.get("expected_redaction_types"):
        if body.get("action") != "redact":
            failures.append("guardrails_response:not_redacted")
    elif body.get("action") != "allow":
        failures.append("guardrails_response:benign_not_allowed")
    return failures


def _check_tracing(case: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    text = case["text"]
    if case.get("expected_redaction_types"):
        checks = {
            "backend_trace": backend_redaction.redact(text).total == 0,
            "guardrails_trace": guardrails_safe_attr("safe_note", text),
            "modelserver_trace": modelserver_tracing.is_safe_span_attribute("safe_note", text),
        }
        failures.extend(surface for surface, safe in checks.items() if safe)
    safe_checks = {
        "backend_trace_length": True,
        "guardrails_trace_length": guardrails_safe_attr("text_length", len(text)),
        "modelserver_trace_length": modelserver_tracing.is_safe_span_attribute("text_length", len(text)),
    }
    failures.extend(surface for surface, safe in safe_checks.items() if not safe)
    return failures


def evaluate_case(client: TestClient, case: dict[str, Any]) -> tuple[bool, list[str]]:
    failures: list[str] = []
    failures.extend(_check_redaction_module("backend", backend_redaction, case))
    failures.extend(_check_redaction_module("guardrails", sys.modules["app.redaction"], case))
    failures.extend(_check_redaction_module("modelserver", modelserver_redaction, case))
    failures.extend(_check_log_filter("backend", backend_redaction.RedactionFilter, case))
    failures.extend(_check_log_filter("guardrails", GuardrailsRedactionFilter, case))
    failures.extend(_check_log_filter("modelserver", modelserver_redaction.RedactionFilter, case))
    failures.extend(_check_guardrails_response(client, case))
    failures.extend(_check_tracing(case))
    return not failures, failures


def append_result(
    output_path: Path,
    status: str,
    observed: float | str,
    threshold: float | str,
    pass_count: int | None = None,
    fail_count: int | None = None,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "gate": GATE_NAME,
        "status": status,
        "observed": observed,
        "threshold": threshold,
    }
    if pass_count is not None and fail_count is not None:
        payload["pass_count"] = pass_count
        payload["fail_count"] = fail_count
    with output_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def main() -> int:
    args = parse_args()
    try:
        threshold = load_required_pass_rate()
        cases = load_cases()
        previous_token = os.environ.get("SERVICE_AUTH_TOKEN")
        os.environ["SERVICE_AUTH_TOKEN"] = SERVICE_TOKEN
        try:
            client = TestClient(guardrails_app)
            failures: list[str] = []
            for case in cases:
                passed, details = evaluate_case(client, case)
                status = "PASS" if passed else "FAIL"
                print(f"[{status}] {case['id']} {case['kind']}")
                failures.extend(f"{case['id']}:{detail}" for detail in details)
        finally:
            if previous_token is None:
                os.environ.pop("SERVICE_AUTH_TOKEN", None)
            else:
                os.environ["SERVICE_AUTH_TOKEN"] = previous_token
        pass_count = len(cases) - len({failure.split(':', 1)[0] for failure in failures})
        fail_count = len(cases) - pass_count
        pass_rate = pass_count / len(cases)
        status = "pass" if pass_rate >= threshold else "fail"
        print(
            f"GATE={GATE_NAME} STATUS={status} OBSERVED={pass_rate:.6f} "
            f"THRESHOLD={threshold:.6f} PASS={pass_count} FAIL={fail_count}"
        )
        if args.output:
            append_result(args.output, status, round(pass_rate, 6), threshold, pass_count, fail_count)
        return 0 if status == "pass" else 1
    except Exception as exc:
        print(f"GATE={GATE_NAME} STATUS=error OBSERVED=NA THRESHOLD=NA")
        print(f"ERROR: {exc.__class__.__name__}", file=sys.stderr)
        if args.output:
            append_result(args.output, "error", "NA", "NA")
        return 2


if __name__ == "__main__":
    sys.exit(main())
