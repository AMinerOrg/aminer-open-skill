#!/usr/bin/env python3
"""
AMiner Open Platform API Client (thin)
Minimal stdlib-only client for the agent-workflow skills in this repository.
Each skill ships its own copy; only SKILL_NAME differs between copies.

Usage:
    python3 scripts/aminer_client.py --action <ACTION> --params '<JSON>'
    (a [Cost] footer is printed to stderr after every call)

Token: read from env AMINER_API_KEY (preferred) or --token <TOKEN>.
Never printed anywhere.

Console (Generate Token): https://open.aminer.cn/open/board?tab=control
Docs: https://open.aminer.cn/open/docs
--params is sent to the API verbatim: use the API's native parameter names.
"""

import argparse
import json
import os
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Optional

BASE_URL = "https://datacenter.aminer.cn/gateway/open_platform"
SKILL_NAME = "aminer-patent-tech-intelligence"  # per-skill copy; only this line differs
SKILL_VERSION = "1.0.1"

REQUEST_TIMEOUT_SECONDS = 30
MAX_RETRIES = 3
RETRYABLE_HTTP_STATUS = {408, 429, 500, 502, 503, 504}

# Actions billed per returned item (unit price × len(data)); IDs not found are free
PER_ITEM_ACTIONS = {"paper_detail_batch"}

# action -> (HTTP method, path, unit price in CNY; 0 = free)
ACTIONS: dict[str, tuple[str, str, float]] = {
    # Paper
    "paper_search": ("GET", "/api/paper/search", 0.0),
    "paper_search_pro": ("GET", "/api/paper/search/pro", 0.01),
    "paper_qa_search": ("POST", "/api/paper/qa/search", 0.05),
    "paper_info": ("POST", "/api/paper/info", 0.0),
    "paper_detail": ("GET", "/api/paper/detail", 0.01),
    "paper_detail_batch": ("POST", "/api/paper/detail/batch", 0.01),  # ¥0.01 per returned paper, ids ≤ 100
    "paper_relation": ("GET", "/api/paper/relation", 0.10),
    # Scholar
    "person_search": ("POST", "/api/person/search", 0.0),
    "person_detail": ("GET", "/api/person/detail", 1.00),
    # Institution
    "org_search": ("POST", "/api/organization/search", 0.0),
    "org_person_relation": ("GET", "/api/organization/person/relation", 0.50),
    "org_paper_relation": ("GET", "/api/organization/paper/relation", 0.10),
    "org_patent_relation": ("GET", "/api/organization/patent/relation", 0.10),
    # Journal / venue
    "venue_search": ("POST", "/api/venue/search", 0.0),
    "venue_detail": ("POST", "/api/venue/detail", 0.20),
    "venue_paper_relation": ("POST", "/api/venue/paper/relation", 0.10),
    # Patent
    "patent_search": ("POST", "/api/patent/search", 0.0),
    "patent_info": ("GET", "/api/patent/info", 0.0),
    "patent_detail": ("GET", "/api/patent/detail", 0.01),
}


def detect_skill_runtime() -> str:
    explicit = (os.environ.get("AMINER_SKILL_RUNTIME") or "").strip().lower().replace("_", "-")
    if explicit:
        return explicit
    if os.environ.get("CLAUDE_CODE") or os.environ.get("CLAUDECODE") or os.environ.get("CLAUDE_PROJECT_DIR"):
        return "claude-code"
    if os.environ.get("CURSOR_TRACE_ID") or os.environ.get("CURSOR_AGENT"):
        return "cursor"
    if os.environ.get("CODEX_HOME") or os.environ.get("CODEX_CLI"):
        return "codex"
    if os.environ.get("OPENCLAW") or os.environ.get("OPENCLAW_HOME"):
        return "openclaw"
    return "unknown"


def _skill_md_version(fallback: str) -> str:
    path = Path(__file__).resolve().parents[1] / "SKILL.md"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return fallback
    if not text.startswith("---"):
        return fallback
    end = text.find("\n---", 3)
    if end < 0:
        return fallback
    for line in text[3:end].splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip() == "version":
            version = value.strip().strip("'\"")
            if version:
                return version
    return fallback


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": token,
        "Content-Type": "application/json;charset=utf-8",
        "X-Platform": detect_skill_runtime(),
        "X-Skill-Name": SKILL_NAME,
        "X-Skill-Version": _skill_md_version(SKILL_VERSION),
    }


def _request(token: str, method: str, path: str,
             params: Optional[dict] = None,
             body: Optional[dict] = None) -> Any:
    """Send an HTTP request and return the parsed JSON data (with retries)."""
    url = BASE_URL + path
    headers = _headers(token)

    if method.upper() == "GET" and params:
        query = urllib.parse.urlencode(
            {k: (json.dumps(v) if isinstance(v, (list, dict)) else v)
             for k, v in params.items() if v is not None}
        )
        url = f"{url}?{query}"

    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())

    last_error_result = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw)
        except urllib.error.HTTPError as e:
            body_bytes = e.read()
            try:
                err = json.loads(body_bytes)
            except Exception:
                err = body_bytes.decode("utf-8", errors="replace")
            retryable = e.code in RETRYABLE_HTTP_STATUS
            print(f"[HTTP {e.code}] {e.reason}: {err}", file=sys.stderr)
            last_error_result = {
                "code": e.code, "success": False,
                "msg": str(e.reason), "error": err, "retryable": retryable,
            }
            if not retryable:
                return last_error_result
        except urllib.error.URLError as e:
            reason = str(getattr(e, "reason", e))
            print(f"[Request failed] {reason}", file=sys.stderr)
            last_error_result = {
                "code": -1, "success": False,
                "msg": "network_error", "error": reason, "retryable": True,
            }
        except TimeoutError as e:
            print(f"[Request timeout] {e}", file=sys.stderr)
            last_error_result = {
                "code": -1, "success": False,
                "msg": "timeout", "error": str(e), "retryable": True,
            }
        except json.JSONDecodeError as e:
            print(f"[Bad JSON response] {e}", file=sys.stderr)
            return {
                "code": -1, "success": False,
                "msg": "bad_json", "error": str(e), "retryable": False,
            }

        if attempt < MAX_RETRIES:
            backoff = (2 ** (attempt - 1)) + random.uniform(0, 0.3)
            print(f"[Retry] attempt={attempt}/{MAX_RETRIES} wait={backoff:.2f}s", file=sys.stderr)
            time.sleep(backoff)

    return last_error_result or {
        "code": -1, "success": False,
        "msg": "request_failed", "error": "max retries exceeded", "retryable": True,
    }


def _cost_footer(actions: list[tuple[str, float]]) -> str:
    total = round(sum(price for _, price in actions), 2)
    breakdown: dict[str, dict[str, Any]] = {}
    for name, price in actions:
        entry = breakdown.setdefault(name, {"calls": 0, "cost": 0.0})
        entry["calls"] += 1
        entry["cost"] = round(entry["cost"] + price, 2)
    parts = [f"{name}: {'Free' if price == 0 else f'¥{price:.2f}'} x{count}"
             for name, (count, price) in
             ((n, (d["calls"], d["cost"])) for n, d in breakdown.items())]
    return f"[Cost] ¥{total:.2f} total, {len(actions)} API calls ({', '.join(parts)})"


def main() -> int:
    parser = argparse.ArgumentParser(description="AMiner Open Platform thin client")
    parser.add_argument("--action", required=True, choices=sorted(ACTIONS),
                        help="API action name (parameters: https://open.aminer.cn/open/docs)")
    parser.add_argument("--params", default="{}",
                        help="JSON object of API parameters, e.g. '{\"query\":\"...\",\"size\":10}'")
    parser.add_argument("--token", default=None,
                        help="API token (prefer env AMINER_API_KEY instead)")
    args = parser.parse_args()

    token = args.token or os.environ.get("AMINER_API_KEY")
    if not token:
        print("AMINER_API_KEY missing. Set the env var or pass --token. "
              "Generate one at https://open.aminer.cn/open/board?tab=control", file=sys.stderr)
        return 2

    try:
        params = json.loads(args.params) if args.params.strip() else {}
        if not isinstance(params, dict):
            raise ValueError("params must be a JSON object")
    except (json.JSONDecodeError, ValueError) as e:
        print(f"Invalid --params: {e}", file=sys.stderr)
        return 2

    method, path, price = ACTIONS[args.action]
    if method == "GET":
        result = _request(token, method, path, params=params)
    else:
        result = _request(token, method, path, body=params)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.action in PER_ITEM_ACTIONS:
        data = result.get("data") if isinstance(result, dict) else None
        price = round(price * (len(data) if isinstance(data, list) else 0), 6)
    print(_cost_footer([(args.action, price)]), file=sys.stderr)
    # Exit codes: 0 = got a response (404 "entity not found" is a valid empty
    # result the skill must read, not a failure); 1 = transport/request failure;
    # 2 = usage or token error.
    if isinstance(result, dict) and result.get("success") is False:
        return 0 if result.get("code") == 404 else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
