from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
GUARDRAILS_ROOT = ROOT / "guardrails"
if str(GUARDRAILS_ROOT) not in sys.path:
    sys.path.insert(0, str(GUARDRAILS_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

GATE_NAME = "redteam_cross_tenant"
FIXTURE_DIR = ROOT / "evals" / "redteam_cross_tenant" / "fixtures"
THRESHOLDS_PATH = ROOT / "eval_thresholds.yaml"
SERVICE_TOKEN = "redteam-eval-token"


def load_required_pass_rate() -> float:
    section: str | None = None
    for raw_line in THRESHOLDS_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if not raw_line.startswith((" ", "\t")) and line.endswith(":"):
            section = line[:-1].strip()
            continue
        if section == "redteam":
            key, separator, value = line.strip().partition(":")
            if separator and key.strip() == "required_pass_rate":
                return float(value.strip())
    raise KeyError(f"missing redteam.required_pass_rate in {THRESHOLDS_PATH}")


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


def evaluate_case(client: TestClient, case: dict[str, Any]) -> tuple[bool, str]:
    path = "/guardrails/output" if case["surface"] == "output" else "/guardrails/input"
    payload: dict[str, Any] = {"text": case["text"]}
    if case.get("context"):
        payload["context"] = case["context"]
    response = client.post(
        path,
        headers={"Authorization": f"Bearer {SERVICE_TOKEN}"},
        json=payload,
    )
    if response.status_code != 200:
        return False, f"status={response.status_code}"
    body = response.json()
    checks = [
        body.get("allowed") == case["expected_allowed"],
        body.get("action") == case["expected_action"],
        set(case.get("expected_categories", [])) <= set(body.get("categories", [])),
    ]
    for raw_value in case.get("must_not_appear", []):
        checks.append(raw_value not in response.text)
    if all(checks):
        return True, "ok"
    return False, (
        f"allowed={body.get('allowed')} action={body.get('action')} "
        f"categories={body.get('categories')}"
    )


def append_result(
    output_path: Path,
    status: str,
    observed: float | str,
    threshold: float | str,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "gate": GATE_NAME,
                    "status": status,
                    "observed": observed,
                    "threshold": threshold,
                },
                sort_keys=True,
            )
            + "\n"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Owner C red-team gate.")
    parser.add_argument("--output", type=Path, help="Optional JSONL result path for CI.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        threshold = load_required_pass_rate()
        cases = load_cases()
        previous_token = os.environ.get("SERVICE_AUTH_TOKEN")
        os.environ["SERVICE_AUTH_TOKEN"] = SERVICE_TOKEN
        try:
            client = TestClient(app)
            failures: list[str] = []
            for case in cases:
                passed, detail = evaluate_case(client, case)
                status = "PASS" if passed else "FAIL"
                print(f"[{status}] {case['id']} {case['category']} {detail}")
                if not passed:
                    failures.append(f"{case['id']}:{detail}")
        finally:
            if previous_token is None:
                os.environ.pop("SERVICE_AUTH_TOKEN", None)
            else:
                os.environ["SERVICE_AUTH_TOKEN"] = previous_token
        pass_count = len(cases) - len(failures)
        pass_rate = pass_count / len(cases)
        status = "pass" if pass_rate >= threshold else "fail"
        print(
            f"GATE={GATE_NAME} STATUS={status} OBSERVED={pass_rate:.6f} "
            f"THRESHOLD={threshold:.6f}"
        )
        if args.output:
            append_result(args.output, status, round(pass_rate, 6), threshold)
        return 0 if status == "pass" else 1
    except Exception as exc:
        print(f"GATE={GATE_NAME} STATUS=error OBSERVED=NA THRESHOLD=NA")
        print(f"ERROR: {exc.__class__.__name__}", file=sys.stderr)
        if args.output:
            append_result(args.output, "error", "NA", "NA")
        return 2


if __name__ == "__main__":
    sys.exit(main())
