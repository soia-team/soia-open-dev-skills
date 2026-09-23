#!/usr/bin/env python3
"""Run one explicitly enabled, typed TypeSafe System One check.

The request is disabled unless --enable-jev is present. --dry-run validates,
scans, path-normalizes, and serializes the request without looking up a key or
opening a network connection. This module uses only the Python standard
library and never retries a request.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import math
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_MODEL = "jev-1.13.0"
MODEL_ID_PATTERN = re.compile(r"(?:jev-[0-9]+\.[0-9]+\.[0-9]+|jev-latest|jev-preview)\Z")
OFFICIAL_HOST = "api.typesafe.ai"
OFFICIAL_AUTHORITY_PATTERN = re.compile(r"(?i)api\.typesafe\.ai(?::443)?\Z")
INPUT_USD_PER_MILLION = 0.042
OUTPUT_USD_PER_MILLION = 0.0
CONFIG_PATH_PARTS = (".config", "soia-skills", "soia-dev-agent-cli-dispatch", "config.yml")
CONFIG_FILE_ENV = "SOIA_DEV_AGENT_CLI_DISPATCH_CONFIG_FILE"
CREDENTIAL_FILE_ENV = "SOIA_DEV_AGENT_CLI_DISPATCH_JEV_CREDENTIAL_FILE"
API_KEY_ENV = "TYPESAFE_API_KEY"
BASE_URL_ENV = "TYPESAFE_BASE_URL"
ENDPOINT_PATH = "/v1/systemone"

EXIT_OK = 0
EXIT_BLOCKED = 2
EXIT_NO_KEY = 3
EXIT_API_ERROR = 4
EXIT_DISABLED = 5
EXIT_INPUT_ERROR = 6

SCAN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("openai_like_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("github_token", re.compile(r"\b(?:gh[pousr]_|github_pat_)[A-Za-z0-9_]{20,}\b")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("slack_token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("bearer_token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{16,}")),
    (
        "jwt",
        re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}\b"),
    ),
    ("pem_private_key", re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")),
    (
        "secret_assignment",
        re.compile(
            r"(?i)\b(?:api[_-]?key|access[_-]?key|client[_-]?secret|private[_-]?key|passwd|password|secret|token)\s*[:=]\s*(?:\"[^\"]+\"|'[^']+'|[^\s,;]+)"
        ),
    ),
    ("cn_id_number", re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")),
    ("cn_mobile", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
    ("bank_card", re.compile(r"(?<!\d)\d{16,19}(?!\d)")),
    (
        "email",
        re.compile(r"\b[A-Za-z0-9._%+-]+@(?!example\.(?:com|org)\b|users\.noreply\.github\.com\b)[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    ),
    ("claim_or_fencing", re.compile(r"(?i)\b(?:CLAIM-[0-9A-F]{8}|lease_id\s*[:=]\s*['\"][^'\"]{8,}|fencing_token\s*[:=]\s*['\"][^'\"]{8,})")),
)
HIGH_ENTROPY_CANDIDATE = re.compile(r"(?<![A-Za-z0-9_])[A-Za-z0-9+/=_-]{32,}(?![A-Za-z0-9_])")
LOCAL_PATH_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"/" + re.escape("Users") + r"/[^/\\\s]+/"),
    re.compile(r"/" + re.escape("home") + r"/[^/\\\s]+/"),
    re.compile(r"(?i)\b[A-Z]:" + re.escape("\\") + re.escape("Users") + re.escape("\\") + r"[^\\/\s]+\\"),
    re.compile(r"(?i)\b[A-Z]:/" + re.escape("Users") + r"/[^/\\\s]+/"),
)
KEY_LIKE_OUTPUT_PATTERNS = tuple(pattern for _, pattern in SCAN_PATTERNS)


class InputError(Exception):
    """Input/configuration could not be used; messages must not include values."""


class InvalidResponse(Exception):
    """The remote response does not match the documented response schema."""


def _result(
    status: str,
    model: str | None = DEFAULT_MODEL,
    *,
    answers: Any = None,
    usage: Any = None,
    cost: Any = None,
    **extra: Any,
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "status": status,
        "model": model,
        "answers": answers,
        "usage": usage,
        "cost_usd_estimate": cost,
    }
    value.update(extra)
    return value


def _print_json(value: dict[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def _parse_yaml_value(raw: str) -> Any:
    """Parse the deliberately small scalar/list subset used by config.example.yml."""
    value = raw.strip()
    if not value:
        return None
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_parse_yaml_value(part) for part in inner.split(",")]
    if value.startswith('"') and value.endswith('"'):
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            raise InputError("invalid private Jev configuration") from exc
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("''", "'")
    if " #" in value:
        value = value.split(" #", 1)[0].rstrip()
    return value


def _parse_jev_config(text: str) -> dict[str, Any]:
    """Read only the jev mapping and its four documented non-secret options."""
    result: dict[str, Any] = {}
    in_jev = False
    jev_indent = -1
    list_key: str | None = None
    list_indent = -1
    allowed = {"credential_file", "keychain_service", "keychain_account", "extra_block_patterns"}

    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()
        if "\t" in raw_line[: len(raw_line) - len(raw_line.lstrip())]:
            raise InputError("invalid private Jev configuration")

        if indent == 0:
            list_key = None
            if line == "jev:":
                in_jev = True
                jev_indent = indent
            else:
                in_jev = False
            continue
        if not in_jev or indent <= jev_indent:
            continue

        if list_key and indent > list_indent and line.startswith("-"):
            item = _parse_yaml_value(line[1:].strip())
            if not isinstance(item, str):
                raise InputError("invalid private Jev configuration")
            result[list_key].append(item)
            continue
        list_key = None

        if ":" not in line:
            continue
        key, raw_value = line.split(":", 1)
        key = key.strip()
        if key not in allowed:
            continue
        parsed = _parse_yaml_value(raw_value)
        if key == "extra_block_patterns":
            if parsed is None:
                result[key] = []
                list_key = key
                list_indent = indent
            elif isinstance(parsed, list) and all(isinstance(item, str) for item in parsed):
                result[key] = parsed
            else:
                raise InputError("invalid private Jev configuration")
        elif parsed is not None:
            if not isinstance(parsed, str):
                raise InputError("invalid private Jev configuration")
            result[key] = parsed
    return result


def _default_config_path() -> Path:
    override = os.environ.get(CONFIG_FILE_ENV)
    if override:
        return Path(override).expanduser()
    return Path.home().joinpath(*CONFIG_PATH_PARTS)


def load_private_config() -> dict[str, Any]:
    path = _default_config_path()
    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeError) as exc:
        raise InputError("could not read private Jev configuration") from exc
    return _parse_jev_config(content)


def _unquote_key(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return value.strip()


def _read_key_file(path_text: str) -> tuple[str | None, bool]:
    path = Path(path_text).expanduser()
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
        broad_permissions = bool(mode & 0o077)
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None, False
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() == API_KEY_ENV:
            key = _unquote_key(value)
            return (key or None), broad_permissions
    return None, broad_permissions


def find_api_key(config: dict[str, Any], environ: dict[str, str]) -> tuple[str | None, list[str]]:
    """Find a key in keychain, configured file, then environment; never print it."""
    warnings: list[str] = []
    service = str(config.get("keychain_service") or "typesafe")
    account = str(config.get("keychain_account") or "api-key")
    security = shutil.which("security") if platform.system() == "Darwin" else None
    if security:
        try:
            completed = subprocess.run(
                [security, "find-generic-password", "-s", service, "-a", account, "-w"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if completed.returncode == 0:
                key = completed.stdout.strip()
                if key:
                    return key, warnings
        except (OSError, subprocess.SubprocessError):
            pass

    credential_path = environ.get(CREDENTIAL_FILE_ENV) or config.get("credential_file")
    if credential_path:
        key, broad_permissions = _read_key_file(str(credential_path))
        if broad_permissions:
            warnings.append("credential_file_permissions_broader_than_0600")
        if key:
            return key, warnings

    key = environ.get(API_KEY_ENV, "").strip()
    return (key or None), warnings


def _shannon_entropy(value: str) -> float:
    if not value:
        return 0.0
    counts: dict[str, int] = {}
    for char in value:
        counts[char] = counts.get(char, 0) + 1
    length = len(value)
    return -sum((count / length) * math.log2(count / length) for count in counts.values())


def _has_high_entropy(text: str) -> int:
    matches = 0
    for match in HIGH_ENTROPY_CANDIDATE.finditer(text):
        value = match.group(0)
        classes = sum(
            bool(re.search(pattern, value))
            for pattern in (r"[a-z]", r"[A-Z]", r"[0-9]", r"[_+/=-]")
        )
        if len(value) >= 32 and classes >= 3 and _shannon_entropy(value) >= 4.0:
            matches += 1
    return matches


def scan_inputs(state: str, questions: dict[str, Any], extra_patterns: list[str] | None = None) -> dict[str, int]:
    texts = (state, json.dumps(questions, ensure_ascii=False, separators=(",", ":")))
    totals: dict[str, int] = {}
    for category, pattern in SCAN_PATTERNS:
        count = sum(len(pattern.findall(item)) for item in texts)
        if count:
            totals[category] = count
    high_entropy_count = sum(_has_high_entropy(item) for item in texts)
    if high_entropy_count:
        totals["high_entropy_string"] = high_entropy_count
    for index, expression in enumerate(extra_patterns or [], start=1):
        try:
            pattern = re.compile(expression)
        except re.error as exc:
            raise InputError("invalid extra Jev scan pattern") from exc
        count = sum(len(pattern.findall(item)) for item in texts)
        if count:
            totals[f"extra_pattern_{index}"] = count
    return totals


def _normalize_string(value: str) -> str:
    for pattern in LOCAL_PATH_PATTERNS:
        value = pattern.sub("~/", value)
    return value


def _normalize_paths(value: Any) -> Any:
    if isinstance(value, str):
        return _normalize_string(value)
    if isinstance(value, list):
        return [_normalize_paths(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalize_paths(item) for key, item in value.items()}
    return value


def _validate_questions(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or not value:
        raise InputError("questions must be a non-empty JSON object")
    for question_id, question in value.items():
        if not isinstance(question_id, str) or not question_id.strip() or not isinstance(question, dict):
            raise InputError("each question must be a named object")
        if any(pattern.search(question_id) for pattern in LOCAL_PATH_PATTERNS):
            raise InputError("question ids must not contain local path forms")
        question_type = question.get("type")
        if question_type not in {"noul", "choice", "score"}:
            raise InputError("question type must be noul, choice, or score")
        if "instructions" not in question or not isinstance(question["instructions"], (str, dict, list)):
            raise InputError("question instructions must be text or structured data")
        criteria = question.get("criteria")
        if question_type == "choice" and (not isinstance(criteria, dict) or not criteria):
            raise InputError("choice questions require a criteria object")
        if question_type == "score" and (not isinstance(criteria, list) or len(criteria) < 2):
            raise InputError("score questions require at least two criteria")
        if question_type == "noul" and criteria is not None and not isinstance(criteria, dict):
            raise InputError("noul criteria must be an object when provided")
    return value


def _read_inputs(state_path: Path, questions_path: Path) -> tuple[str, dict[str, Any]]:
    try:
        state = state_path.read_text(encoding="utf-8")
        questions = json.loads(questions_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise InputError("could not read state or parse questions JSON") from exc
    return state, _validate_questions(questions)


def _request_object(state: str, questions: dict[str, Any], model: str) -> dict[str, Any]:
    return {"model": model, "state": state, "questions": questions}


def _request_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _endpoint(base_url: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(base_url)
        valid = (
            parsed.scheme.lower() == "https"
            and OFFICIAL_AUTHORITY_PATTERN.fullmatch(parsed.netloc) is not None
            and "@" not in parsed.netloc
            and not parsed.query
            and not parsed.fragment
            and "?" not in base_url
            and "#" not in base_url
        )
    except ValueError as exc:
        raise InputError("TYPESAFE_BASE_URL must use the official HTTPS host") from exc
    if not valid:
        raise InputError("TYPESAFE_BASE_URL must use the official HTTPS host")
    return urllib.parse.urlunsplit(("https", OFFICIAL_HOST, parsed.path.rstrip("/") + ENDPOINT_PATH, "", ""))


def _redact_text(value: str, key: str | None = None) -> str:
    result = value
    if key:
        result = result.replace(key, "[redacted]")
    result = _normalize_string(result)
    for pattern in KEY_LIKE_OUTPUT_PATTERNS:
        result = pattern.sub("[redacted]", result)
    return result[:1000]


def _redact_typed_value(value: Any, key: str) -> Any:
    if isinstance(value, str):
        return _redact_text(value, key)
    if isinstance(value, list):
        return [_redact_typed_value(item, key) for item in value]
    if isinstance(value, dict):
        result = {}
        for name, item in value.items():
            safe_name = _redact_text(name, key) if isinstance(name, str) else name
            if safe_name in result:
                raise InvalidResponse("redacted response keys collide")
            result[safe_name] = _redact_typed_value(item, key)
        return result
    return value


def _is_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    return isinstance(value, float) and math.isfinite(value)


def _string_map(value: Any) -> dict[str, str]:
    if not isinstance(value, dict) or not value or any(not isinstance(name, str) or not isinstance(item, str) for name, item in value.items()):
        raise InvalidResponse("invalid response string map")
    return value


def _number_map(value: Any) -> dict[str, int | float]:
    if not isinstance(value, dict) or not value or any(not isinstance(name, str) or not _is_number(item) for name, item in value.items()):
        raise InvalidResponse("invalid response number map")
    return value


def _rebuild_response(decoded: Any, questions: dict[str, Any], key: str) -> dict[str, Any]:
    """Rebuild only documented response fields and IDs present in the request."""
    if not isinstance(decoded, dict):
        raise InvalidResponse("invalid response object")
    raw_model = decoded.get("model")
    raw_answers = decoded.get("answers")
    raw_usage = decoded.get("usage")
    if not isinstance(raw_model, str) or not raw_model or not isinstance(raw_answers, dict) or not isinstance(raw_usage, dict):
        raise InvalidResponse("invalid response envelope")

    answers: dict[str, dict[str, Any]] = {}
    for question_id, question in questions.items():
        raw_answer = raw_answers.get(question_id)
        expected_type = question["type"]
        if not isinstance(raw_answer, dict) or raw_answer.get("type") != expected_type:
            raise InvalidResponse("missing or mismatched answer")
        if expected_type == "noul":
            if not _is_number(raw_answer.get("noul")):
                raise InvalidResponse("invalid noul answer")
            answer = {"type": "noul", "noul": raw_answer["noul"]}
        elif expected_type == "choice":
            if not isinstance(raw_answer.get("choice"), str) or not raw_answer.get("choice") or not _is_number(raw_answer.get("confidence")):
                raise InvalidResponse("invalid choice answer")
            answer = {
                "type": "choice",
                "choice": raw_answer["choice"],
                "probabilities": _number_map(raw_answer.get("probabilities")),
                "confidence": raw_answer["confidence"],
            }
        else:
            if not _is_number(raw_answer.get("score")) or not _is_number(raw_answer.get("confidence")):
                raise InvalidResponse("invalid score answer")
            answer = {
                "type": "score",
                "score": raw_answer["score"],
                "legend": _string_map(raw_answer.get("legend")),
                "probabilities": _number_map(raw_answer.get("probabilities")),
                "confidence": raw_answer["confidence"],
            }
        answers[question_id] = answer

    usage: dict[str, int] = {}
    for field in ("input_tokens", "output_tokens"):
        value = raw_usage.get(field)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            usage[field] = value

    rebuilt = {"model": raw_model, "answers": answers, "usage": usage}
    return _redact_typed_value(rebuilt, key)


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Refuse every redirect so Authorization can never move to another URL."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _usage_cost(usage: Any) -> dict[str, Any]:
    if not isinstance(usage, dict):
        return {
            "value": None,
            "basis": "TypeSafe published input-token price estimate; unavailable because input token usage was not returned",
            "reason": "response did not include a valid usage.input_tokens value",
            "input_usd_per_1m": INPUT_USD_PER_MILLION,
            "output_usd_per_1m": OUTPUT_USD_PER_MILLION,
        }
    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
    if isinstance(input_tokens, bool) or not isinstance(input_tokens, int) or input_tokens < 0:
        estimate: float | None = None
    else:
        estimate = input_tokens * INPUT_USD_PER_MILLION / 1_000_000
    if isinstance(output_tokens, int) and not isinstance(output_tokens, bool) and output_tokens >= 0:
        estimate = (estimate or 0.0) + output_tokens * OUTPUT_USD_PER_MILLION / 1_000_000 if estimate is not None else None
    result = {
        "value": estimate,
        "basis": "TypeSafe published input-token price estimate; output tokens are free",
        "input_usd_per_1m": INPUT_USD_PER_MILLION,
        "output_usd_per_1m": OUTPUT_USD_PER_MILLION,
    }
    if estimate is None:
        result["reason"] = "response did not include a valid usage.input_tokens value"
    return result


def _http_error_class(status_code: int) -> str:
    return {
        401: "unauthorized",
        403: "forbidden",
        422: "invalid_request",
        429: "rate_limited",
    }.get(status_code, "server_error" if 500 <= status_code <= 599 else "http_error")


def _error_fields(body: bytes, key: str) -> dict[str, str]:
    try:
        parsed = json.loads(body.decode("utf-8", errors="replace"))
    except (UnicodeError, json.JSONDecodeError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    error = parsed.get("error", parsed)
    if not isinstance(error, dict):
        return {}
    result: dict[str, str] = {}
    for field in ("code", "message"):
        value = error.get(field)
        if isinstance(value, (str, int, float)) and not isinstance(value, bool):
            result[field] = _redact_text(str(value), key)
    return result


def _api_error(status_code: int, body: bytes, key: str) -> dict[str, Any]:
    error = _result(
        "api_error",
        http_status=status_code,
        error_class=_http_error_class(status_code),
        error=_error_fields(body, key),
    )
    return error


def _send_request(url: str, payload: dict[str, Any], key: str, timeout: float) -> dict[str, Any]:
    try:
        request = urllib.request.Request(
            url,
            data=_request_bytes(payload),
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        opener = urllib.request.build_opener(NoRedirectHandler)
        with opener.open(request, timeout=timeout) as response:
            raw = response.read()
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise InvalidResponse("invalid JSON response") from exc
        rebuilt = _rebuild_response(decoded, payload["questions"], key)
        usage = rebuilt["usage"]
        return _result(
            "ok",
            rebuilt["model"],
            answers=rebuilt["answers"],
            usage=usage,
            cost=_usage_cost(usage),
        )
    except urllib.error.HTTPError as exc:
        if 300 <= int(exc.code) <= 399:
            return _result(
                "api_error",
                http_status=int(exc.code),
                error_class="redirect_refused",
                error={"message": "redirect refused"},
            )
        try:
            body = exc.read(65536)
        except OSError:
            body = b""
        return _api_error(int(exc.code), body, key)
    except InvalidResponse:
        return _result("api_error", error_class="invalid_response", error={"message": "invalid response shape"})
    except (KeyError, TypeError, ValueError):
        return _result("api_error", error_class="invalid_response", error={"message": "invalid response shape"})
    except (urllib.error.URLError, TimeoutError, OSError):
        return _result("api_error", error_class="network_or_response_error", error={"message": "request failed"})
    except Exception:
        # Do not stringify unknown exceptions: transports may include headers or payloads.
        return _result("api_error", error_class="request_error", error={"message": "request failed"})


def _load_checked_inputs(args: argparse.Namespace, config: dict[str, Any]) -> tuple[str, dict[str, Any], dict[str, int]]:
    if not args.state_file or not args.questions_file:
        raise InputError("--state-file and --questions-file are required")
    state, questions = _read_inputs(args.state_file, args.questions_file)
    extras = config.get("extra_block_patterns", [])
    if not isinstance(extras, list) or any(not isinstance(item, str) for item in extras):
        raise InputError("invalid extra Jev scan configuration")
    findings = scan_inputs(state, questions, extras)
    return state, questions, findings


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        _print_json(_result("input_error"))
        raise SystemExit(EXIT_INPUT_ERROR)


def build_parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Exit codes: 0=ok; 2=blocked_by_scan; 3=skipped_no_key; "
            "4=api_error/network_error; 5=disabled; 6=input_error. "
            "No request is sent unless --enable-jev is present."
        ),
    )
    parser.add_argument("--enable-jev", action="store_true", help="Enable one external request; scanning remains mandatory.")
    parser.add_argument("--dry-run", action="store_true", help="Scan and package without a key lookup or network request.")
    parser.add_argument("--state-file", type=Path, help="File containing the candidate material to classify.")
    parser.add_argument("--questions-file", type=Path, help="JSON file containing a TypeSafe typed questions map.")
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Model id jev-N.N.N or jev-latest/jev-preview (default: {DEFAULT_MODEL}).",
    )
    parser.add_argument("--timeout", type=float, default=30.0, help="Per-request timeout in seconds (default: 30).")
    parser.add_argument("--selftest", action="store_true", help="Run offline tests with mocked credentials and transport.")
    return parser


def _main(args: argparse.Namespace) -> int:
    if args.selftest:
        return run_selftest()
    model = args.model if isinstance(args.model, str) and MODEL_ID_PATTERN.fullmatch(args.model) else None
    if model is None:
        _print_json(_result("input_error", None))
        return EXIT_INPUT_ERROR
    if args.dry_run:
        if not math.isfinite(args.timeout) or args.timeout <= 0:
            _print_json(_result("input_error", model))
            return EXIT_INPUT_ERROR
        try:
            config = load_private_config()
            state, questions, findings = _load_checked_inputs(args, config)
            if findings:
                _print_json(_result("blocked_by_scan", model, scan_categories=findings))
                return EXIT_BLOCKED
            payload = _request_object(
                _normalize_string(state),
                _normalize_paths(questions),
                model,
            )
            _print_json(
                _result(
                    "dry_run",
                    model,
                    request_bytes=len(_request_bytes(payload)),
                    question_count=len(questions),
                )
            )
            return EXIT_OK
        except InputError:
            _print_json(_result("input_error", model))
            return EXIT_INPUT_ERROR

    if not args.enable_jev:
        _print_json(_result("disabled", model))
        return EXIT_DISABLED
    if not args.state_file or not args.questions_file:
        _print_json(_result("input_error", model))
        return EXIT_INPUT_ERROR
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        _print_json(_result("input_error", model))
        return EXIT_INPUT_ERROR

    try:
        config = load_private_config()
        state, questions, findings = _load_checked_inputs(args, config)
    except InputError:
        _print_json(_result("input_error", model))
        return EXIT_INPUT_ERROR
    if findings:
        _print_json(_result("blocked_by_scan", model, scan_categories=findings))
        return EXIT_BLOCKED

    try:
        endpoint = _endpoint(os.environ.get(BASE_URL_ENV, "https://api.typesafe.ai"))
    except InputError:
        _print_json(_result("input_error", model))
        return EXIT_INPUT_ERROR

    try:
        key, warnings = find_api_key(config, os.environ)
    except InputError:
        _print_json(_result("input_error", model))
        return EXIT_INPUT_ERROR
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    if not key:
        _print_json(_result("skipped_no_key", model))
        return EXIT_NO_KEY

    payload = _request_object(
        _normalize_string(state),
        _normalize_paths(questions),
        model,
    )
    result = _send_request(endpoint, payload, key, args.timeout)
    _print_json(result)
    return EXIT_OK if result.get("status") == "ok" else EXIT_API_ERROR


def _capture_main(argv: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = main(argv)
    return code, stdout.getvalue(), stderr.getvalue()


def run_selftest() -> int:
    """Offline boundary tests. A unique temporary directory is always removed."""
    import unittest.mock as mock

    temp_root = Path(tempfile.mkdtemp(prefix="soia-dev-agent-cli-dispatch-jev-"))
    checks: list[tuple[str, bool]] = []
    sensitive_observables: list[str] = []

    def record(name: str, condition: bool) -> None:
        checks.append((name, bool(condition)))

    try:
        state_file = temp_root / "state.txt"
        questions_file = temp_root / "questions.json"
        state_file.write_text("Review this public patch summary.", encoding="utf-8")
        questions_file.write_text(
            json.dumps(
                {"has_issue": {"type": "noul", "instructions": "Does the candidate violate the stated rule?"}},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        code, stdout, stderr = _capture_main(["--state-file", str(state_file), "--questions-file", str(questions_file)])
        record("default is disabled and nonzero", code == EXIT_DISABLED and '"status":"disabled"' in stdout and not stderr)

        with mock.patch(__name__ + ".load_private_config", return_value={}):
            code, stdout, stderr = _capture_main(
                ["--dry-run", "--state-file", str(state_file), "--questions-file", str(questions_file)]
            )
        dry = json.loads(stdout)
        record(
            "dry-run packages without a key or network",
            code == EXIT_OK and dry.get("status") == "dry_run" and dry.get("question_count") == 1 and dry.get("request_bytes", 0) > 0 and not stderr,
        )

        keychain_key = "KEYCHAIN_SENTINEL_7f91b3"
        file_key = "FILE_SENTINEL_28c4ad"
        env_key = "ENV_SENTINEL_3a10ef"
        credential_file = temp_root / "credential.env"
        credential_file.write_text(f"# ignored\n{API_KEY_ENV}={file_key}\n", encoding="utf-8")
        credential_file.chmod(0o600)

        with mock.patch("platform.system", return_value="Darwin"), mock.patch("shutil.which", return_value="security"), mock.patch(
            "subprocess.run", return_value=subprocess.CompletedProcess([], 0, keychain_key + "\n", "")
        ) as security_run:
            found, warnings = find_api_key(
                {"credential_file": str(credential_file)},
                {CREDENTIAL_FILE_ENV: str(credential_file), API_KEY_ENV: env_key},
            )
        record(
            "keychain is first and key is not an argv item",
            found == keychain_key
            and not warnings
            and security_run.call_args.args[0][-1] == "-w"
            and security_run.call_args.args[0][1:6] == ["find-generic-password", "-s", "typesafe", "-a", "api-key"]
            and keychain_key not in security_run.call_args.args[0],
        )

        with mock.patch("platform.system", return_value="Darwin"), mock.patch("shutil.which", return_value="security"), mock.patch(
            "subprocess.run", return_value=subprocess.CompletedProcess([], 1, "", "")
        ):
            found_file, _ = find_api_key(
                {"credential_file": str(credential_file)},
                {API_KEY_ENV: env_key},
            )
        record("credential file is second", found_file == file_key)

        credential_file.chmod(0o644)
        with mock.patch("platform.system", return_value="Linux"):
            found_file, permission_warnings = find_api_key(
                {"credential_file": str(credential_file)},
                {},
            )
        record(
            "broad credential-file permissions only warn",
            found_file == file_key and permission_warnings == ["credential_file_permissions_broader_than_0600"],
        )

        with mock.patch("platform.system", return_value="Linux"), mock.patch("shutil.which") as which:
            found_env, _ = find_api_key({}, {API_KEY_ENV: env_key})
        record("environment variable is final fallback and non-mac skips keychain", found_env == env_key and not which.called)

        scanned_state = "candidate contains sk" + "-" + "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        state_file.write_text(scanned_state, encoding="utf-8")
        with mock.patch(__name__ + ".load_private_config", return_value={}), mock.patch(
            __name__ + ".find_api_key"
        ) as blocked_key_lookup, mock.patch(__name__ + "._send_request") as blocked_send:
            code, stdout, stderr = _capture_main(
                ["--enable-jev", "--state-file", str(state_file), "--questions-file", str(questions_file)]
            )
        blocked = json.loads(stdout)
        sensitive_observables.extend((stdout, stderr, json.dumps(blocked)))
        record(
            "scanner blocks before key lookup and request and prints category counts only",
            code == EXIT_BLOCKED
            and blocked.get("status") == "blocked_by_scan"
            and blocked.get("scan_categories", {}).get("openai_like_key") == 1
            and "ABCDEFGHIJKLMNOPQRSTUVWXYZ" not in stdout
            and blocked_key_lookup.call_count == 0
            and blocked_send.call_count == 0
            and not stderr,
        )
        combined_findings = scan_inputs(
            "password" + "=" + "sample secret-value token" + "=" + "abc api_key" + "=" + "privatevalue "
            "eyJabcdefghijk.abcdefghijk.abcdefghi "
            "-----BEGIN RSA PRIVATE KEY----- "
            "123456789012345678X 13812345678 1234567890123456 person" + "@" + "example.net CLAIM-ABCD1234 "
            "aBcD0123EfGh4567IjKl8901MnOp2345 FORBIDDEN_WORD",
            {"q": {"type": "noul", "instructions": "check this"}},
            ["FORBIDDEN_WORD"],
        )
        record(
            "scanner covers assignments, JWT, PEM, entropy, and configured patterns",
            all(
                name in combined_findings
                for name in (
                    "secret_assignment", "jwt", "pem_private_key", "high_entropy_string",
                    "cn_id_number", "cn_mobile", "bank_card", "email", "claim_or_fencing", "extra_pattern_1"
                )
            ),
        )

        unix_users = "/" + "Users" + "/example-user/work/file"
        unix_home = "/" + "home" + "/sample/project"
        windows_users = "C:" + "\\" + "Users" + "\\person\\repo"
        normalized = _normalize_paths("unix " + unix_users + " and " + unix_home + " plus " + windows_users)
        record("Unix and Windows local paths are rewritten", normalized == "unix ~/work/file and ~/project plus ~/repo")

        state_file.write_text("Inspect a safe public diff.", encoding="utf-8")
        question_map = _validate_questions(json.loads(questions_file.read_text(encoding="utf-8")))
        request = _request_object("~/repo/diff", _normalize_paths(question_map), DEFAULT_MODEL)
        packaged = json.loads(_request_bytes(request).decode("utf-8"))
        record(
            "request uses the official top-level shape and pinned model",
            set(packaged) == {"model", "state", "questions"}
            and packaged["model"] == DEFAULT_MODEL
            and packaged["state"] == "~/repo/diff"
            and isinstance(packaged["questions"], dict),
        )

        parsed_config = _parse_jev_config(
            "jev:\n"
            "  credential_file: \"<credential-file-path>\"\n"
            "  keychain_service: typesafe\n"
            "  keychain_account: api-key\n"
            "  extra_block_patterns:\n"
            "    - FORBIDDEN_WORD\n"
        )
        record(
            "private Jev config reads only supported non-secret settings",
            parsed_config.get("credential_file") == "<credential-file-path>"
            and parsed_config.get("keychain_service") == "typesafe"
            and parsed_config.get("keychain_account") == "api-key"
            and parsed_config.get("extra_block_patterns") == ["FORBIDDEN_WORD"],
        )

        with mock.patch(__name__ + ".load_private_config", return_value={}), mock.patch(
            __name__ + ".find_api_key", return_value=(None, [])
        ), mock.patch(__name__ + "._send_request") as missing_key_send:
            code, stdout, stderr = _capture_main(
                ["--enable-jev", "--state-file", str(state_file), "--questions-file", str(questions_file)]
            )
        record(
            "missing key is skipped with exit code three",
            code == EXIT_NO_KEY
            and json.loads(stdout).get("status") == "skipped_no_key"
            and missing_key_send.call_count == 0
            and not stderr,
        )

        invalid_questions = temp_root / "invalid-questions.json"
        invalid_questions.write_text("{", encoding="utf-8")
        code, stdout, stderr = _capture_main(
            ["--dry-run", "--state-file", str(state_file), "--questions-file", str(invalid_questions)]
        )
        record(
            "invalid inputs have a fixed status and exit code",
            code == EXIT_INPUT_ERROR and json.loads(stdout).get("status") == "input_error" and not stderr,
        )
        path_question = {"/" + "Users" + "/example-user/item": {"type": "noul", "instructions": "Check this."}}
        windows_path_question = {"C:" + "\\" + "Users" + "\\person\\item": {"type": "noul", "instructions": "Check this."}}
        path_ids_rejected = True
        home_path_question = {"/" + "home" + "/example/item": next(iter(path_question.values()))}
        for value in (path_question, home_path_question, windows_path_question):
            try:
                _validate_questions(value)
                path_ids_rejected = False
            except InputError:
                pass
        record("question IDs with Unix or Windows local paths are rejected unchanged", path_ids_rejected)

        secret_key = "EXPOSURE_SECRET_SENTINEL_82ca71"
        code, stdout, stderr = _capture_main(["--model", secret_key])
        invalid_model_result = json.loads(stdout)
        sensitive_observables.extend((stdout, stderr, json.dumps(invalid_model_result)))
        record(
            "invalid model is rejected without echoing its value",
            code == EXIT_INPUT_ERROR
            and invalid_model_result.get("status") == "input_error"
            and invalid_model_result.get("model") is None
            and secret_key not in stdout + stderr,
        )
        record(
            "only pinned IDs and official aliases pass model validation",
            all(MODEL_ID_PATTERN.fullmatch(model) for model in ("jev-1.13.0", "jev-2.0.3", "jev-latest", "jev-preview"))
            and all(not MODEL_ID_PATTERN.fullmatch(model) for model in ("latest", "jev-1.13", "jev-1.13.0/extra", secret_key)),
        )

        record(
            "HTTP status classes are distinct",
            [_http_error_class(code) for code in (401, 403, 422, 429, 500, 529, 503)]
            == ["unauthorized", "forbidden", "invalid_request", "rate_limited", "server_error", "server_error", "server_error"]
            and all(_api_error(code, b"{}", "fake").get("http_status") == code for code in (401, 403, 422, 429, 500, 529, 503)),
        )
        rejected_bases = (
            "http://api.typesafe.ai",
            "https://example.invalid",
            "https://@api.typesafe.ai",
            "https://user:pass@api.typesafe.ai",
            "https://api.typesafe.ai:8443",
            "https://api.t\u00fdpesafe.ai",
            "https://api%2etypesafe%2eai",
        )
        rejected_all = True
        for base in rejected_bases:
            try:
                _endpoint(base)
                rejected_all = False
            except InputError:
                pass
        accepted_prefix = _endpoint("https://api.typesafe.ai/gateway/v2")
        accepted_default_port = _endpoint("https://api.typesafe.ai:443/gateway")
        record(
            "base URL pins the official host and rejects userinfo, nondefault ports, IDN and encoded hosts",
            rejected_all
            and accepted_prefix == "https://api.typesafe.ai/gateway/v2/v1/systemone"
            and accepted_default_port == "https://api.typesafe.ai/gateway/v1/systemone",
        )

        with mock.patch.dict(os.environ, {BASE_URL_ENV: "https://example.invalid"}, clear=False), mock.patch(
            __name__ + ".load_private_config", return_value={}
        ), mock.patch(__name__ + ".find_api_key") as rejected_host_key_lookup, mock.patch(
            __name__ + "._send_request"
        ) as rejected_host_send:
            host_code, host_stdout, host_stderr = _capture_main(
                ["--enable-jev", "--state-file", str(state_file), "--questions-file", str(questions_file)]
            )
        host_result = json.loads(host_stdout)
        sensitive_observables.extend((host_stdout, host_stderr, json.dumps(host_result)))
        record(
            "nonofficial host is rejected before key lookup or request",
            host_code == EXIT_INPUT_ERROR
            and host_result.get("status") == "input_error"
            and rejected_host_key_lookup.call_count == 0
            and rejected_host_send.call_count == 0
            and not host_stderr,
        )

        class FakeResponse(io.BytesIO):
            pass

        success_payload = {
            "model": secret_key,
            "answers": {
                "has_issue": {"type": "noul", "noul": 0.2, secret_key: "unapproved answer field"},
                secret_key: {"type": "noul", "noul": 0.9},
            },
            "usage": {"input_tokens": 1000, "output_tokens": 20, secret_key: 1},
            secret_key: "unapproved top-level field",
        }
        request_calls: list[urllib.request.Request] = []

        class FakeOpener:
            def __init__(self, response_bytes: bytes | None = None, error: Exception | None = None):
                self.response_bytes = response_bytes
                self.error = error
                self.requests: list[urllib.request.Request] = []

            def open(self, request_obj: urllib.request.Request, timeout: float) -> FakeResponse:
                self.requests.append(request_obj)
                if self.error is not None:
                    raise self.error
                return FakeResponse(self.response_bytes or b"")

        success_opener = FakeOpener(json.dumps(success_payload).encode("utf-8"))

        with mock.patch(__name__ + ".load_private_config", return_value={}), mock.patch(
            __name__ + ".find_api_key", return_value=(secret_key, [])
        ), mock.patch("urllib.request.build_opener", return_value=success_opener) as opener_mock:
            code, stdout, stderr = _capture_main(
                ["--enable-jev", "--state-file", str(state_file), "--questions-file", str(questions_file)]
            )
        success = json.loads(stdout)
        request_calls = success_opener.requests
        sent = json.loads(request_calls[0].data.decode("utf-8")) if request_calls else {}
        sensitive_observables.extend((stdout, stderr, json.dumps(success)))
        if request_calls:
            sensitive_observables.append(request_calls[0].full_url)
        record(
            "response is rebuilt from official fields and response keys cannot expose a secret",
            code == EXIT_OK
            and success.get("status") == "ok"
            and success.get("model") == "[redacted]"
            and set(success.get("answers", {})) == {"has_issue"}
            and set(success["answers"]["has_issue"]) == {"type", "noul"}
            and set(success.get("usage", {})) == {"input_tokens", "output_tokens"}
            and success.get("cost_usd_estimate", {}).get("value") == 0.000042
            and secret_key not in stdout + stderr + json.dumps(success)
            and opener_mock.call_count == 1
            and len(request_calls) == 1
            and request_calls[0].get_header("Authorization") == f"Bearer {secret_key}"
            and request_calls[0].get_method() == "POST"
            and request_calls[0].full_url == "https://api.typesafe.ai/v1/systemone"
            and sent.get("model") == DEFAULT_MODEL,
        )

        choice_response = _rebuild_response(
            {
                "model": "jev-1.13.0",
                "answers": {
                    "choice_q": {
                        "type": "choice",
                        "choice": "yes",
                        "probabilities": {secret_key: 0.75, "no": 0.25},
                        "confidence": 0.75,
                    }
                },
                "usage": {"input_tokens": 10, "output_tokens": 1},
            },
            {"choice_q": {"type": "choice", "criteria": {"yes": "Yes", "no": "No"}}},
            secret_key,
        )
        choice_response_json = json.dumps(choice_response)
        sensitive_observables.append(choice_response_json)
        record(
            "a secret embedded in an allowed response map key is redacted",
            secret_key not in choice_response_json
            and "[redacted]" in choice_response["answers"]["choice_q"]["probabilities"],
        )

        redirect_path = "https://api.typesafe.ai/gateway/redirect-refused"
        redirect_error = urllib.error.HTTPError(
            "https://api.typesafe.ai/v1/systemone",
            302,
            "Found",
            {"Location": redirect_path},
            io.BytesIO(b""),
        )
        redirect_opener = FakeOpener(error=redirect_error)
        with mock.patch(__name__ + ".load_private_config", return_value={}), mock.patch(
            __name__ + ".find_api_key", return_value=(secret_key, [])
        ), mock.patch("urllib.request.build_opener", return_value=redirect_opener) as redirect_builder:
            redirect_code, redirect_stdout, redirect_stderr = _capture_main(
                ["--enable-jev", "--state-file", str(state_file), "--questions-file", str(questions_file)]
            )
        redirect_result = json.loads(redirect_stdout)
        redirect_request = redirect_opener.requests[0] if redirect_opener.requests else None
        redirect_handler_class = redirect_builder.call_args.args[0] if redirect_builder.call_args else None
        redirect_handler = redirect_handler_class() if redirect_handler_class is NoRedirectHandler else None
        configured_redirect_handlers = [
            handler for handler in urllib.request.build_opener(NoRedirectHandler).handlers
            if isinstance(handler, urllib.request.HTTPRedirectHandler)
        ]
        redirect_followup = (
            redirect_handler.redirect_request(redirect_request, None, 302, "Found", {"Location": redirect_path}, redirect_path)
            if redirect_handler is not None and redirect_request is not None
            else "handler missing"
        )
        sensitive_observables.extend(
            (redirect_stdout, redirect_stderr, json.dumps(redirect_result), redirect_path)
        )
        if redirect_request is not None:
            sensitive_observables.append(redirect_request.full_url)
        record(
            "redirect returns redirect_refused, never follows or forwards Authorization, and emits no secret",
            redirect_code == EXIT_API_ERROR
            and redirect_result.get("status") == "api_error"
            and redirect_result.get("error_class") == "redirect_refused"
            and redirect_result.get("http_status") == 302
            and redirect_opener.requests and len(redirect_opener.requests) == 1
            and redirect_handler_class is NoRedirectHandler
            and len(configured_redirect_handlers) == 1
            and isinstance(configured_redirect_handlers[0], NoRedirectHandler)
            and redirect_followup is None
            and redirect_request is not None
            and redirect_request.get_header("Authorization") == f"Bearer {secret_key}"
            and secret_key not in redirect_stdout + redirect_stderr + json.dumps(redirect_result)
            and secret_key not in redirect_request.full_url
            and secret_key not in redirect_path,
        )

        echoed_key = "ERROR_ECHO_SECRET_SENTINEL_8f3c12"
        error_body = json.dumps({"error": {"code": "invalid_key", "message": f"rejected {echoed_key}"}}).encode("utf-8")
        error_obj = urllib.error.HTTPError("https://api.typesafe.ai/v1/systemone", 401, "Unauthorized", {}, io.BytesIO(error_body))
        error_opener = FakeOpener(error=error_obj)
        request = _request_object("safe state", json.loads(questions_file.read_text(encoding="utf-8")), DEFAULT_MODEL)
        with mock.patch("urllib.request.build_opener", return_value=error_opener):
            api_error = _send_request("https://api.typesafe.ai/v1/systemone", request, echoed_key, 30)
        encoded_error = json.dumps(api_error)
        sensitive_observables.append(encoded_error)
        record(
            "HTTP error reads only code/message and redacts the key",
            api_error.get("status") == "api_error"
            and api_error.get("http_status") == 401
            and api_error.get("error_class") == "unauthorized"
            and "invalid_key" in encoded_error
            and echoed_key not in encoded_error,
        )

        exception_key = "TRANSPORT_SENTINEL_49a5de"
        failure_opener = FakeOpener(error=RuntimeError(f"transport echoed {exception_key}"))
        with mock.patch("urllib.request.build_opener", return_value=failure_opener):
            failed = _send_request("https://api.typesafe.ai/v1/systemone", request, exception_key, 30)
        sensitive_observables.append(json.dumps(failed))
        record(
            "exception output is generic and transport is never retried",
            failed.get("status") == "api_error"
            and exception_key not in json.dumps(failed)
            and len(failure_opener.requests) == 1,
        )

        malformed_opener = FakeOpener(
            json.dumps({"model": DEFAULT_MODEL, "answers": {}, "usage": {"input_tokens": 1, "output_tokens": 1}}).encode("utf-8")
        )
        with mock.patch("urllib.request.build_opener", return_value=malformed_opener):
            malformed_response = _send_request("https://api.typesafe.ai/v1/systemone", request, secret_key, 30)
        record(
            "response schema mismatch maps to invalid_response",
            malformed_response.get("status") == "api_error" and malformed_response.get("error_class") == "invalid_response",
        )

        partial_usage_response = _rebuild_response(
            {
                "model": "jev-1.13.0",
                "answers": {"has_issue": {"type": "noul", "noul": 0.0}},
                "usage": {"output_tokens": 59},
            },
            {"has_issue": {"type": "noul"}},
            secret_key,
        )
        partial_usage_cost = _usage_cost(partial_usage_response["usage"])
        record(
            "partial usage keeps the valid output count and makes cost null with a reason",
            partial_usage_response["usage"] == {"output_tokens": 59}
            and partial_usage_cost["value"] is None
            and "usage.input_tokens" in partial_usage_cost["reason"],
        )

        empty_usage_response = _rebuild_response(
            {
                "model": "jev-1.13.0",
                "answers": {"has_issue": {"type": "noul", "noul": 0.0}},
                "usage": {},
            },
            {"has_issue": {"type": "noul"}},
            secret_key,
        )
        empty_usage_cost = _usage_cost(empty_usage_response["usage"])
        record(
            "empty usage is valid and makes cost null with a reason",
            empty_usage_response["usage"] == {}
            and empty_usage_cost["value"] is None
            and "usage.input_tokens" in empty_usage_cost["reason"],
        )

        sentinels = (keychain_key, file_key, env_key, secret_key, echoed_key, exception_key)
        external_outputs_are_clean = all(
            secret not in item for secret in sentinels for item in sensitive_observables
        )
        transcript_before_final_check = "=== jev_check.py selftest ===\n" + "\n".join(
            f"[{ 'PASS' if passed else 'FAIL' }] {name}" for name, passed in checks
        )
        transcript_candidate = transcript_before_final_check + (
            "\n[PASS] sentinel strings are absent from report and every external output channel"
            if external_outputs_are_clean
            else "\n[FAIL] sentinel strings are absent from report and every external output channel"
        )
        transcript_is_clean = all(secret not in transcript_candidate for secret in sentinels)
        record(
            "sentinel strings are absent from report and every external output channel",
            external_outputs_are_clean and transcript_is_clean,
        )
        transcript = "=== jev_check.py selftest ===\n" + "\n".join(
            f"[{ 'PASS' if passed else 'FAIL' }] {name}" for name, passed in checks
        )
        # Capture and inspect the exact bytes printed by this selftest, including its final assertion.
        rendered = io.StringIO()
        with contextlib.redirect_stdout(rendered):
            print(transcript)
        actual_transcript = rendered.getvalue()
        if any(secret in actual_transcript for secret in sentinels):
            checks[-1] = (checks[-1][0], False)
            rendered = io.StringIO()
            with contextlib.redirect_stdout(rendered):
                print("=== jev_check.py selftest ===")
                for name, passed in checks:
                    print(f"[{ 'PASS' if passed else 'FAIL' }] {name}")
            actual_transcript = rendered.getvalue()
        print(actual_transcript, end="")
        return 0 if all(passed for _, passed in checks) else 1
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return _main(args)


if __name__ == "__main__":
    raise SystemExit(main())
