#!/usr/bin/env python
"""Headless entry point for the e-mail reminders — run DAILY by GitHub Actions.

Sends, to every approved user:
  * the weekly briefing — deduplicated per ISO week, so running this every day
    still delivers it once, on the first run of the week (Monday);
  * the one-shot alert for deadlines that passed yesterday — which is precisely
    why this has to run daily and not only on Mondays.

SMTP settings are read from the `settings` row in Supabase, so the only secrets
this needs are SUPABASE_URL / SUPABASE_KEY.

Exit codes: 0 = ran (even if nothing had to be sent), 1 = misconfigured or failed.
"""

import os
import sys

# Allow "python scripts/send_reminders.py" from the repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.scheduler import check_and_send_deadline_reminders  # noqa: E402


def main() -> int:
    if not (os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_KEY")):
        print("::error::SUPABASE_URL / SUPABASE_KEY are not set.")
        return 1

    result = check_and_send_deadline_reminders()

    if result.get("error"):
        print(f"::error::Scheduler failed: {result['error']}")
        return 1

    if result.get("skipped"):
        # Not a crash, but nothing was sent and the user should know why.
        print(f"::warning::Nothing sent — {result['skipped']} (check Admin → Settings).")
        return 1

    print(
        f"Weekly briefings sent: {result['briefings_sent']} · "
        f"Overdue alerts sent: {result['alerts_sent']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
