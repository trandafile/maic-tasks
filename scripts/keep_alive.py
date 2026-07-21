#!/usr/bin/env python
"""Keep the free-tier services from going to sleep.

* **Supabase** — a free project is paused after ~7 days without activity.
  One tiny read is enough to reset that timer.
* **Streamlit Community Cloud** — an app sleeps after a long stretch with no
  traffic. A periodic HTTP GET counts as traffic. NOTE: it reliably keeps an
  *awake* app awake, but it cannot be relied on to *wake* one that is already
  asleep — that screen wants a real click.

Deliberately dependency-free (standard library only). A keep-alive is
infrastructure: it must not break when the app code or its dependencies do,
so it does NOT import db.py / the supabase package.

Environment:
    SUPABASE_URL          required
    SUPABASE_KEY          required
    STREAMLIT_APP_URL     optional; skip the app ping when unset
    KEEPALIVE_TABLE       optional; table to read (default: settings)

Exit codes: 0 = Supabase reached, 1 = Supabase unreachable/misconfigured.
A failed Streamlit ping is reported but never fails the run: the database is
what actually gets paused, and losing the job over a flaky HTTP call would
silently stop the Supabase keep-alive too.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request

TIMEOUT = 20
RETRIES = 3
RETRY_WAIT = 5  # seconds; a cold free-tier instance can take a moment


def _get(url: str, headers: dict, label: str) -> tuple[bool, str]:
    """GET with retries. Returns (ok, detail)."""
    last = ""
    for attempt in range(1, RETRIES + 1):
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                body = resp.read(400).decode("utf-8", "replace")
                return True, f"HTTP {resp.status} · {body[:120]}"
        except urllib.error.HTTPError as e:
            # A 4xx is a real answer: the service is awake, just unhappy.
            detail = e.read(300).decode("utf-8", "replace") if e.fp else ""
            last = f"HTTP {e.code} · {detail[:160]}"
            if e.code in (401, 403):
                return False, last  # bad credentials: retrying cannot help
            if 400 <= e.code < 500:
                return True, last + "  (service responded → it is awake)"
        except Exception as e:  # URLError, timeout, DNS…
            last = f"{type(e).__name__}: {e}"
        if attempt < RETRIES:
            print(f"  {label}: attempt {attempt} failed ({last}) — retrying…")
            time.sleep(RETRY_WAIT)
    return False, last


def ping_supabase(url: str, key: str, table: str) -> bool:
    endpoint = f"{url.rstrip('/')}/rest/v1/{table}?select=id&limit=1"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
        "User-Agent": "maic-tasks-keepalive/1.0",
    }
    ok, detail = _get(endpoint, headers, "supabase")
    print(f"Supabase [{table}]: {'OK' if ok else 'FAILED'} — {detail}")
    return ok


def ping_streamlit(app_url: str) -> bool:
    headers = {"User-Agent": "maic-tasks-keepalive/1.0"}
    ok, detail = _get(app_url, headers, "streamlit")
    print(f"Streamlit [{app_url}]: {'OK' if ok else 'FAILED'} — {detail}")
    return ok


def main() -> int:
    url = os.environ.get("SUPABASE_URL", "").strip()
    key = os.environ.get("SUPABASE_KEY", "").strip()
    table = os.environ.get("KEEPALIVE_TABLE", "settings").strip() or "settings"
    app_url = os.environ.get("STREAMLIT_APP_URL", "").strip()

    if not (url and key):
        print("::error::SUPABASE_URL / SUPABASE_KEY are not set.")
        return 1

    db_ok = ping_supabase(url, key, table)

    if app_url:
        if not ping_streamlit(app_url):
            # Non-fatal on purpose — see the module docstring.
            print("::warning::Streamlit ping failed; the Supabase keep-alive still counts.")
    else:
        print("Streamlit: skipped (STREAMLIT_APP_URL not set).")

    if not db_ok:
        print("::error::Supabase did not respond — the project may be paused already.")
        return 1

    print("Keep-alive done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
