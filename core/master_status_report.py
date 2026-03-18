from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass

from core.supabase_client import supabase


def _date_sort_key(value: str | None) -> tuple[int, str]:
    # nulls last
    return (1, "9999-12-31") if not value else (0, value)


def _uname(users_by_email: dict[str, dict], email: str | None) -> str:
    if not email:
        return "—"
    u = users_by_email.get(email)
    if u:
        return u.get("name") or email
    return email


@dataclass(frozen=True)
class MasterStatusPayload:
    markdown: str
    by_project: list[tuple[str, str]]  # [(project_name, markdown_block)]


def build_master_status_report_markdown(show_archived: bool = False) -> MasterStatusPayload:
    """Build an admin-oriented Markdown report.

    Hierarchy:
    Project -> Deliverables -> Tasks -> Subtasks
    plus orphan tasks (no deliverable) under each project.
    """
    # Projects
    pq = supabase.table("projects").select("*").order("name")
    if not show_archived:
        pq = pq.eq("is_archived", False)
    projects = pq.execute().data or []

    # Deliverables
    dq = supabase.table("deliverables").select("*").order("deadline")
    if not show_archived:
        dq = dq.eq("is_archived", False)
    deliverables = dq.execute().data or []

    # Tasks
    tq = supabase.table("tasks").select("*").order("sort_order", desc=False)
    if not show_archived:
        tq = tq.eq("is_archived", False)
    tasks = tq.execute().data or []

    # Subtasks
    sq = supabase.table("subtasks").select("*").order("sort_order", desc=False)
    if not show_archived:
        sq = sq.eq("is_archived", False)
    subtasks = sq.execute().data or []

    # Users for name resolution
    uq = supabase.table("users").select("email, name").eq("is_approved", True)
    users = uq.execute().data or []
    users_by_email = {u["email"]: u for u in users if u.get("email")}

    # Indexes
    deliverables_by_project: dict[int, list[dict]] = {}
    for d in deliverables:
        pid = d.get("project_id")
        if pid is None:
            continue
        deliverables_by_project.setdefault(pid, []).append(d)

    tasks_by_deliverable: dict[int, list[dict]] = {}
    orphan_tasks_by_project: dict[int, list[dict]] = {}
    for t in tasks:
        pid = t.get("project_id")
        did = t.get("deliverable_id")
        if pid is None:
            continue
        if did:
            tasks_by_deliverable.setdefault(did, []).append(t)
        else:
            orphan_tasks_by_project.setdefault(pid, []).append(t)

    subtasks_by_task: dict[int, list[dict]] = {}
    for s in subtasks:
        tid = s.get("task_id")
        if not tid:
            continue
        subtasks_by_task.setdefault(tid, []).append(s)

    def _sort_tasks(items: list[dict]) -> list[dict]:
        return sorted(
            items,
            key=lambda x: (
                _date_sort_key(x.get("deadline")),
                x.get("sort_order") if x.get("sort_order") is not None else 999999,
                x.get("id") or 0,
            ),
        )

    def _sort_subtasks(items: list[dict]) -> list[dict]:
        return sorted(
            items,
            key=lambda x: (
                _date_sort_key(x.get("deadline")),
                x.get("sort_order") if x.get("sort_order") is not None else 999999,
                x.get("id") or 0,
            ),
        )

    def _append_task_block(lines: list[str], t: dict) -> None:
        seq = t.get("sequence_id") or f"T-{t.get('id', '?')}"
        t_name = t.get("name", "")
        t_status = t.get("status", "Not started")
        t_dead = t.get("deadline") or "—"
        t_owner = _uname(users_by_email, t.get("owner_email"))
        t_notes = (t.get("notes") or "").strip()

        lines.append(f"> ### {seq} — {t_name} ({t_status}, Deadline {t_dead}, {t_owner})")
        lines.append("> ")
        if t_notes:
            for ln in t_notes.splitlines():
                lines.append(f"> {ln}")
        else:
            lines.append("> No task notes provided.")
        lines.append("> ")

        t_subs = _sort_subtasks(subtasks_by_task.get(t.get("id") or 0, []))
        for s in t_subs:
            s_name = s.get("name", "")
            s_status = s.get("status", "Not started")
            s_dead = s.get("deadline") or "—"
            s_owner = _uname(users_by_email, s.get("owner_email"))
            chk = "x" if s_status == "Completed" else " "
            lines.append(f"> - [{chk}] {s_name} ({s_status}, Deadline {s_dead}, {s_owner})")
        lines.append("")

    blocks: list[tuple[str, str]] = []
    all_lines: list[str] = []

    gen_date = _dt.date.today().isoformat()
    all_lines.append(f"<!-- Generated: {gen_date} -->")
    all_lines.append("")

    for p in projects:
        pid = p.get("id")
        if pid is None:
            continue

        p_name = p.get("name", "Project")
        p_desc = (p.get("description") or "").strip()

        lines: list[str] = []
        lines.append(f"# {p_name}")
        lines.append("")
        lines.append(f"*{p_desc}*" if p_desc else "*No description provided.*")
        lines.append("")

        p_delivs = deliverables_by_project.get(pid, [])
        p_delivs = sorted(
            p_delivs,
            key=lambda d: (_date_sort_key(d.get("deadline")), d.get("id") or 0),
        )

        for d in p_delivs:
            d_name = d.get("name", "Deliverable")
            d_dead = d.get("deadline") or "—"
            d_owner = _uname(users_by_email, d.get("owner_email"))
            d_desc = (d.get("description") or "").strip()

            lines.append(f"## Deliverable: {d_name} (Deadline {d_dead}, {d_owner})")
            lines.append("")
            lines.append(d_desc if d_desc else "No deliverable description provided.")
            lines.append("")

            d_tasks = _sort_tasks(tasks_by_deliverable.get(d.get("id") or 0, []))
            for t in d_tasks:
                _append_task_block(lines, t)

        orphans = _sort_tasks(orphan_tasks_by_project.get(pid, []))
        if orphans:
            lines.append("## Orphan Tasks (No Deliverable)")
            lines.append("")
            for t in orphans:
                _append_task_block(lines, t)

        block = "\n".join(lines).strip() + "\n"
        blocks.append((p_name, block))
        all_lines.append(block)
        all_lines.append("\n---\n")

    full_md = "\n".join(all_lines).rstrip() + "\n"
    return MasterStatusPayload(markdown=full_md, by_project=blocks)

