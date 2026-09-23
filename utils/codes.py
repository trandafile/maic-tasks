"""utils/codes.py — readable identifiers: E, E.1, E.1.2, E.1.2.1.

    E        project letter (one per ACTIVE project; I and O excluded)
    E.1      deliverable 1 of project E
    E.1.2    task 2 of deliverable E.1          (E.0.n = task with no deliverable)
    E.1.2.1  subtask 1 of task E.1.2

Rules
* The database stores integers (projects.code_letter, *.code_no); the dotted
  code is composed from them, so it always matches the current parent chain.
* A number is proposed (first free after the highest in use) and may be
  changed by hand, provided it is free: no other item of the same parent —
  archived ones included — holds it. Unique indexes in the database refuse
  duplicates whatever the path.
* Numbers are identity, not position: they are never recomputed to close
  gaps, so a code quoted in an e-mail keeps meaning the same thing.
* Moving a task to another deliverable gives it a number there and keeps the
  old code in ``code_history``.
* The composed code is also written to ``sequence_id`` (``resync_project``),
  the field e-mails, PDFs, calendar and reports already display.
"""

from __future__ import annotations

import re
import time

from core.supabase_client import supabase

LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ"          # no I, no O: they read as 1 and 0
CODE_RE = re.compile(r"^[A-Z](\.\d+)+$")

_AVAILABLE = {"ok": None, "at": 0.0}


def numbering_available() -> bool:
    """True once the numbering migration has run. Re-probed every minute so
    running the migration takes effect without restarting the app."""
    now = time.time()
    if _AVAILABLE["ok"] is not None and now - _AVAILABLE["at"] < 60:
        return _AVAILABLE["ok"]
    try:
        supabase.table("tasks").select("code_no").limit(1).execute()
        ok = True
    except Exception:
        ok = False
    _AVAILABLE.update(ok=ok, at=now)
    return ok


def fmt(letter: str | None, *nums) -> str:
    """'E', 1, 2 → 'E.1.2'. Empty when the letter or any number is missing."""
    if not letter or any(n is None for n in nums):
        return ""
    return ".".join([letter] + [str(int(n)) for n in nums])


def is_code(value) -> bool:
    return bool(value) and bool(CODE_RE.match(str(value)))


# ── used / free numbers ───────────────────────────────────────────────────────

def _nos(rows) -> set[int]:
    return {int(r["code_no"]) for r in rows if r.get("code_no") is not None}


def used_deliverable_nos(project_id: int) -> set[int]:
    try:
        return _nos(supabase.table("deliverables").select("code_no").eq(
            "project_id", project_id).execute().data or [])
    except Exception:
        return set()


def used_task_nos(project_id: int, deliverable_id: int | None) -> set[int]:
    try:
        q = supabase.table("tasks").select("code_no").eq("project_id", project_id)
        q = q.eq("deliverable_id", deliverable_id) if deliverable_id else \
            q.is_("deliverable_id", "null")
        return _nos(q.execute().data or [])
    except Exception:
        return set()


def used_subtask_nos(task_id: int) -> set[int]:
    try:
        return _nos(supabase.table("subtasks").select("code_no").eq(
            "task_id", task_id).execute().data or [])
    except Exception:
        return set()


def next_free(used: set[int]) -> int:
    return (max(used) + 1) if used else 1


def check_free(n, used: set[int], own: int | None = None) -> str | None:
    """None when ``n`` can be used, else the reason."""
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "The number must be a whole number."
    if n < 1:
        return "The number must be 1 or more."
    if n != own and n in used:
        return (f"Number {n} is already taken here. Free: {next_free(used)} "
                f"(or any gap)." if used else "")
    return None


# ── project letters ───────────────────────────────────────────────────────────

def taken_letters(exclude_project_id: int | None = None) -> dict[str, str]:
    """{letter: project name} for ACTIVE projects."""
    try:
        rows = supabase.table("projects").select(
            "id, name, acronym, code_letter").eq("is_archived", False).execute().data or []
    except Exception:
        return {}
    return {r["code_letter"]: (r.get("acronym") or r.get("name") or "?")
            for r in rows if r.get("code_letter") and r["id"] != exclude_project_id}


def propose_letter(project: dict, taken) -> str | None:
    """The acronym's first usable letter if free, then its other letters, then
    the name's, then the first free letter of the alphabet."""
    taken = set(taken)
    for source in (project.get("acronym"), project.get("name")):
        for ch in (source or "").upper():
            if ch in LETTERS and ch not in taken:
                return ch
    return next((ch for ch in LETTERS if ch not in taken), None)


def propose_all(projects: list[dict]) -> dict[int, str]:
    """Letters for the active projects that have none, without collisions."""
    taken = {p["code_letter"] for p in projects
             if p.get("code_letter") and not p.get("is_archived")}
    out: dict[int, str] = {}
    for p in sorted(projects, key=lambda p: (p.get("acronym") or p.get("name") or "").lower()):
        if p.get("is_archived") or p.get("code_letter"):
            continue
        ch = propose_letter(p, taken)
        if ch:
            out[p["id"]] = ch
            taken.add(ch)
    return out


# ── keep sequence_id (what the rest of the app displays) in step ──────────────

def resync_project(project_id: int) -> int:
    """Rewrite sequence_id of the project's tasks and subtasks to their
    current code. Only rows that differ are written. Returns how many."""
    if not numbering_available():
        return 0
    try:
        proj = supabase.table("projects").select("code_letter").eq(
            "id", project_id).execute().data or []
        letter = (proj[0] or {}).get("code_letter") if proj else None
        if not letter:
            return 0
        dnos = {d["id"]: d.get("code_no") for d in (supabase.table("deliverables").select(
            "id, code_no").eq("project_id", project_id).execute().data or [])}
        tasks = supabase.table("tasks").select(
            "id, deliverable_id, code_no, sequence_id").eq(
            "project_id", project_id).execute().data or []
        subs = []
        if tasks:
            try:
                subs = supabase.table("subtasks").select(
                    "id, task_id, code_no, sequence_id").in_(
                    "task_id", [t["id"] for t in tasks]).execute().data or []
            except Exception:
                subs = []
    except Exception as exc:
        print(f"[codes.resync_project] {exc}")
        return 0

    n = 0
    tcode = {}
    for t in tasks:
        dno = dnos.get(t.get("deliverable_id")) if t.get("deliverable_id") else 0
        code = fmt(letter, dno, t.get("code_no"))
        tcode[t["id"]] = (dno, t.get("code_no"))
        if code and code != t.get("sequence_id"):
            try:
                supabase.table("tasks").update({"sequence_id": code}).eq("id", t["id"]).execute()
                n += 1
            except Exception as exc:
                print(f"[codes.resync_project] task {t['id']}: {exc}")
    for s in subs:
        dno, tno = tcode.get(s.get("task_id"), (None, None))
        code = fmt(letter, dno, tno, s.get("code_no"))
        if code and code != s.get("sequence_id"):
            try:
                supabase.table("subtasks").update({"sequence_id": code}).eq("id", s["id"]).execute()
                n += 1
            except Exception as exc:
                print(f"[codes.resync_project] subtask {s['id']}: {exc}")
    return n


def append_history(old_history: str | None, old_code: str | None) -> str | None:
    """'E.1.3' added to a comma list of former codes (no duplicates)."""
    if not old_code:
        return old_history
    parts = [p.strip() for p in (old_history or "").split(",") if p.strip()]
    if old_code not in parts:
        parts.append(old_code)
    return ", ".join(parts)
