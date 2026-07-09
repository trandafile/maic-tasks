import streamlit as st
import datetime
import json
import html as _html
from core.supabase_client import supabase
from db import (
    get_settings, log_status_change,
    get_comments, add_comment, update_comment, delete_comment,
)
from utils.md_editor import markdown_editor
from utils.notifications import send_task_assigned, send_task_comment
from utils.helpers import parse_deliverable_tag_styles


def _fmt_date(d: str | None) -> str:
    """Format an ISO date string as DD/MM/YYYY, or return '—' if missing."""
    if not d:
        return "—"
    try:
        return datetime.date.fromisoformat(d).strftime("%d/%m/%Y")
    except Exception:
        return d or "—"

def get_status_color_map():
    return {
        "Not started": "⚪ Not started",
        "Working on": "🟡 Working on",
        "Blocked": "🔴 Blocked",
        "Completed": "🟢 Completed",
        "Cancelled": "⚫ Cancelled"
    }

def render_priority_badge(priority: str) -> str:
    if not priority:
        return "⚪ None"
    p = priority.lower()
    if p == "urgent":
        return "🔴 Urgent"
    elif p == "high":
        return "🟠 High"
    elif p == "medium":
        return "🔵 Medium"
    elif p == "low":
        return "🟢 Low"
    return f"⚪ {priority.capitalize()}"


# ── Shared person-pill helper ─────────────────────────────────────────────────

def person_pill_html(name: str, color: str, role: str = "owner",
                     compact: bool = False) -> str:
    """
    Colored avatar pill chip for owner/supervisor display.

    role: "owner" → violet pill
          "sup"   → amber pill
    compact: True  → compact spacing but still shows full name
    """
    parts = (name or "").split()
    if len(parts) >= 2:
        initials = (parts[0][0] + parts[-1][0]).upper()
    elif parts:
        initials = parts[0][:2].upper()
    else:
        initials = "?"

    if role == "owner":
        bg_pill  = "#EEEDFE"
        border   = "#AFA9EC"
        av_bg    = "#534AB7"
        av_fg    = "#EEEDFE"
        lbl_col  = "#3C3489"
        name_col = "#3C3489"
        lbl_text = "owner"
    else:  # sup
        bg_pill  = "#FAEEDA"
        border   = "#FAC775"
        av_bg    = "#BA7517"
        av_fg    = "#FAEEDA"
        lbl_col  = "#633806"
        name_col = "#633806"
        lbl_text = "sup"

    av_size = 16 if compact else 20
    av_fs   = 8 if compact else 9
    av_html = (
        f"<span style='background:{av_bg};color:{av_fg};border-radius:50%;"
        f"width:{av_size}px;height:{av_size}px;display:inline-flex;align-items:center;"
        f"justify-content:center;font-size:{av_fs}px;font-weight:700;"
        f"flex-shrink:0;'>{initials}</span>"
    )

    if compact:
        return (
            f"<span style='display:inline-flex;align-items:center;gap:4px;"
            f"padding:1px 6px 1px 3px;border-radius:99px;"
            f"background:{bg_pill};border:1px solid {border};"
            f"margin-right:4px;' title='{role}: {name}'>"
            f"{av_html}"
            f"<span style='font-size:10px;color:{name_col};line-height:1.1'>{name}</span>"
            f"</span>"
        )

    return (
        f"<span style='display:inline-flex;align-items:center;gap:4px;"
        f"padding:3px 8px 3px 4px;border-radius:99px;"
        f"background:{bg_pill};border:1px solid {border};"
        f"margin-right:6px;'>"
        f"{av_html}"
        f"<span style='font-size:10px;font-weight:700;color:{lbl_col};"
        f"margin:0 1px;'>{lbl_text}</span>"
        f"<span style='font-size:12px;color:{name_col};'>{name}</span>"
        f"</span>"
    )


# ── Context fetchers for modals ───────────────────────────────────────────────

def _fetch_task_ctx(task: dict):
    """Return (proj_dict, deliv_dict, user_map) for a task row."""
    proj: dict = {}
    deliv: dict = {}
    user_map: dict = {}
    try:
        if task.get("project_id"):
            res = supabase.table("projects").select("name, acronym").eq(
                "id", task["project_id"]
            ).execute().data
            proj = res[0] if res else {}
        if task.get("deliverable_id"):
            res = supabase.table("deliverables").select("name").eq(
                "id", task["deliverable_id"]
            ).execute().data
            deliv = res[0] if res else {}
        emails = [e for e in [task.get("owner_email"), task.get("supervisor_email")] if e]
        if emails:
            res = supabase.table("users").select("email, name, avatar_color").in_(
                "email", emails
            ).execute().data
            user_map = {u["email"]: u for u in res}
    except Exception:
        pass
    return proj, deliv, user_map


def _fetch_subtask_ctx(subtask: dict):
    """Return (parent_task_dict, proj_dict, deliv_dict, user_map) for a subtask row."""
    parent: dict = {}
    proj: dict = {}
    deliv: dict = {}
    user_map: dict = {}
    try:
        if subtask.get("task_id"):
            t_res = supabase.table("tasks").select(
                "id, name, sequence_id, project_id, deliverable_id"
            ).eq("id", subtask["task_id"]).execute().data
            parent = t_res[0] if t_res else {}
            if parent.get("project_id"):
                p_res = supabase.table("projects").select("name, acronym").eq(
                    "id", parent["project_id"]
                ).execute().data
                proj = p_res[0] if p_res else {}
            if parent.get("deliverable_id"):
                d_res = supabase.table("deliverables").select("name").eq(
                    "id", parent["deliverable_id"]
                ).execute().data
                deliv = d_res[0] if d_res else {}
        emails = [e for e in [subtask.get("owner_email"), subtask.get("supervisor_email")] if e]
        if emails:
            res = supabase.table("users").select("email, name, avatar_color").in_(
                "email", emails
            ).execute().data
            user_map = {u["email"]: u for u in res}
    except Exception:
        pass
    return parent, proj, deliv, user_map


def _breadcrumb_html(
    seq_id: str,
    proj: dict,
    deliv: dict,
    parent_task: dict | None = None,
) -> str:
    """Build breadcrumb HTML for a modal header (hierarchy only, no item name)."""
    acronym = proj.get("acronym") or proj.get("name", "")
    proj_name = proj.get("name", "")

    parts: list[str] = []
    if proj_name:
        parts.append(f"<b>{acronym}</b>: {proj_name}" if acronym else proj_name)
    if deliv:
        parts.append(deliv.get("name", ""))
    if parent_task:
        pt_name = parent_task.get("name", "")
        if pt_name:
            parts.append(pt_name)

    prefix = " &rsaquo; ".join(parts)
    current = f"{seq_id}"

    if prefix:
        return (
            f"<div style='font-size:11px;color:#888;margin-bottom:6px;line-height:1.7;'>"
            f"{prefix} &rsaquo; "
            f"<span style='color:#1a73e8;font-weight:500;'>{current}</span></div>"
        )
    return (
        f"<div style='font-size:11px;color:#1a73e8;font-weight:500;"
        f"margin-bottom:6px;'>{current}</div>"
    )


def _persons_pills_html(
    user_map: dict,
    owner_email: str | None,
    sup_email: str | None,
) -> str:
    """Build owner/supervisor pills HTML block."""
    pills = ""
    if owner_email:
        u = user_map.get(owner_email, {"name": owner_email, "avatar_color": "#888888"})
        pills += person_pill_html(
            u.get("name", owner_email),
            u.get("avatar_color", "#888888"),
            role="owner",
            compact=False,
        )
    if sup_email and sup_email != owner_email:
        u = user_map.get(sup_email, {"name": sup_email, "avatar_color": "#888888"})
        pills += person_pill_html(
            u.get("name", sup_email),
            u.get("avatar_color", "#888888"),
            role="sup",
            compact=False,
        )
    return f"<div style='margin-bottom:4px;'>{pills}</div>" if pills else ""


# ── Internal helpers ──────────────────────────────────────────────────────────

def _fetch_all_users() -> list[dict]:
    """Fetch all approved users ordered by name."""
    try:
        return supabase.table("users").select("email, name").eq(
            "is_approved", True
        ).order("name").execute().data or []
    except Exception:
        return []


def _user_opts(all_users: list[dict]) -> dict[str, str]:
    """Build {display_label: email} dict from user list."""
    return {f"{u['name']} ({u['email']})": u["email"] for u in all_users}


def _find_display(opts: dict[str, str], email: str | None) -> str | None:
    """Return the display label for the given email, or None if not found."""
    if not email:
        return None
    return next((k for k, v in opts.items() if v == email), None)


def _parse_date(value: str | None) -> datetime.date | None:
    if not value:
        return None
    try:
        return datetime.date.fromisoformat(value)
    except (ValueError, TypeError):
        return None


# ── Comments thread ───────────────────────────────────────────────────────────

def _fmt_comment_ts(value: str | None) -> str:
    if not value:
        return ""
    try:
        clean = str(value).replace("Z", "+00:00")
        return datetime.datetime.fromisoformat(clean).strftime("%d/%m/%Y %H:%M")
    except Exception:
        return str(value)[:16].replace("T", " ")


def _can_edit_comment(comment: dict) -> bool:
    """A comment can be edited/deleted by its author or by any admin."""
    if st.session_state.get("user_role") == "admin":
        return True
    me = st.session_state.get("user_email")
    return bool(me) and comment.get("author_email") == me


# Callbacks run BEFORE the rerun, so the dialog re-renders with fresh data
# without us calling st.rerun() (which would close the dialog).

def _delete_comment_cb(comment_id: int):
    delete_comment(comment_id)
    st.session_state.pop(f"_edit_comment_{comment_id}", None)


def _start_edit_comment_cb(comment_id: int):
    st.session_state[f"_edit_comment_{comment_id}"] = True


def _cancel_edit_comment_cb(comment_id: int):
    st.session_state.pop(f"_edit_comment_{comment_id}", None)
    st.session_state.pop(f"_edit_body_{comment_id}", None)


def _save_edit_comment_cb(comment_id: int):
    body = st.session_state.get(f"_edit_body_{comment_id}", "")
    ok, _ = update_comment(comment_id, body)
    if ok:
        st.session_state.pop(f"_edit_comment_{comment_id}", None)
        st.session_state.pop(f"_edit_body_{comment_id}", None)


def _notify_comment(task: dict, author_email: str | None, body: str, project_name: str | None):
    """Email the task owner and supervisor (except the comment's author)."""
    author_name = st.session_state.get("user_name") or author_email or "Someone"
    enriched = {**task, "project_name": project_name or task.get("project_name", "")}
    recipients = {
        e for e in (task.get("owner_email"), task.get("supervisor_email"))
        if e and e != author_email
    }
    for e in recipients:
        try:
            send_task_comment(enriched, e, author_name, body)
        except Exception as exc:  # never let a mail failure break the post
            print(f"[modals._notify_comment] {exc}")


def _render_one_comment(c: dict, me: str | None):
    cid = c.get("id")
    is_system = bool(c.get("is_system_event"))
    author = c.get("author_name") or c.get("author_email") or "?"
    ts = _fmt_comment_ts(c.get("created_at"))

    if st.session_state.get(f"_edit_comment_{cid}") and not is_system:
        st.text_area(
            "Edit comment", value=c.get("body", ""), key=f"_edit_body_{cid}",
            height=80, label_visibility="collapsed",
        )
        e1, e2, _ = st.columns([1, 1, 4])
        e1.button("💾 Save", key=f"_csave_{cid}", on_click=_save_edit_comment_cb, args=(cid,))
        e2.button("Cancel", key=f"_ccancel_{cid}", on_click=_cancel_edit_comment_cb, args=(cid,))
        return

    dot = "#2E7D32" if is_system else "#1565C0"
    st.html(
        f"<div style='display:flex;align-items:flex-start;gap:8px;padding:6px 0;"
        f"border-bottom:1px solid #f2f2f2'>"
        f"<span style='width:8px;height:8px;border-radius:50%;background:{dot};"
        f"margin-top:6px;flex-shrink:0'></span>"
        f"<div style='flex:1'>"
        f"<div style='font-size:11px;color:#888'>"
        f"<b style='color:#444'>{_html.escape(str(author))}</b>"
        f"{'  · system' if is_system else ''} · {ts}</div>"
        f"<div style='font-size:13px;color:#222;white-space:pre-wrap'>"
        f"{_html.escape(c.get('body','') or '')}</div>"
        f"</div></div>"
    )
    if not is_system and _can_edit_comment(c):
        b1, b2, _ = st.columns([1, 1, 6])
        b1.button("✏️ Edit", key=f"_cedit_{cid}", on_click=_start_edit_comment_cb, args=(cid,))
        b2.button("🗑️ Delete", key=f"_cdel_{cid}", on_click=_delete_comment_cb, args=(cid,))


def _render_task_comments(task: dict, can_edit: bool, project_name: str | None = None):
    """Discussion thread for a task. Posting is restricted to admin / owner /
    supervisor (``can_edit``); everyone viewing the task can read it."""
    task_id = task.get("id")
    if not task_id:
        return
    me = st.session_state.get("user_email")

    st.markdown("---")

    # Placeholder so the thread renders ABOVE the input but is filled AFTER the
    # post is processed (so a just-posted comment shows without st.rerun).
    thread_box = st.container()

    if can_edit:
        with st.form(f"comment_form_{task_id}", clear_on_submit=True):
            new_body = st.text_area(
                "Add a comment", key=f"_new_comment_{task_id}", height=80,
                label_visibility="collapsed", placeholder="Write a comment…",
            )
            posted = st.form_submit_button("💬 Post comment", type="primary")
        if posted:
            if not (new_body or "").strip():
                st.warning("Comment is empty.")
            else:
                ok, err = add_comment(task_id, me, new_body)
                if ok:
                    _notify_comment(task, me, new_body, project_name)
                    st.toast("Comment posted")
                else:
                    st.error(f"Could not post: {err}")
    elif me:
        st.caption("Only the task owner, supervisor or an admin can post comments.")

    comments = get_comments(task_id, include_system=True)
    user_comments = [c for c in comments if not c.get("is_system_event")]
    with thread_box:
        st.markdown(f"**💬 Comments ({len(user_comments)})**")
        if not comments:
            st.caption("No comments yet.")
        for c in comments:
            _render_one_comment(c, me)


# ── Modals ────────────────────────────────────────────────────────────────────

@st.dialog("Task Details", width="large")
def task_details_modal(task, can_edit, deliverables=None):
    # ── Header: breadcrumb → name → persons ──────────────────────────────────
    proj, deliv, user_map = _fetch_task_ctx(task)
    seq_id = task.get("sequence_id") or f"T-{task.get('id')}"
    st.html(_breadcrumb_html(seq_id=seq_id, proj=proj, deliv=deliv))

    curr_name = task.get("name", "") or ""
    pills_html = _persons_pills_html(
        user_map=user_map,
        owner_email=task.get("owner_email"),
        sup_email=task.get("supervisor_email"),
    )
    status_map = get_status_color_map()

    if can_edit:
        # ── Fetch supporting data ─────────────────────────────────────────────
        if deliverables is None:
            res = supabase.table("deliverables").select("id, name, project_id").eq(
                "project_id", task.get("project_id")
            ).execute()
            deliverables = res.data or []

        all_users = _fetch_all_users()
        user_opts = _user_opts(all_users)

        status_options = list(status_map.keys())
        display_options = list(status_map.values())

        curr_status = task.get("status") or "Not started"
        if curr_status not in status_options:
            curr_status = "Not started"

        deliv_opts = {d["name"]: d["id"] for d in deliverables}
        deliv_opts["None (Generic)"] = None
        curr_deliv_id = task.get("deliverable_id")
        curr_deliv_name = next((k for k, v in deliv_opts.items() if v == curr_deliv_id), "None (Generic)")

        owner_keys = list(user_opts.keys())
        curr_owner_disp = _find_display(user_opts, task.get("owner_email"))
        owner_idx = owner_keys.index(curr_owner_disp) if curr_owner_disp in owner_keys else 0

        sup_keys = ["None"] + owner_keys
        curr_sup_disp = _find_display(user_opts, task.get("supervisor_email")) or "None"
        sup_idx = sup_keys.index(curr_sup_disp) if curr_sup_disp in sup_keys else 0

        curr_deadline = _parse_date(task.get("deadline"))

        # Admins can reassign; non-admin owners/supervisors keep current assignment
        _is_admin_modal = st.session_state.get("user_role") == "admin"

        # ── Edit form ─────────────────────────────────────────────────────────
        # The form is essential: the markdown editor syncs its content into a
        # hidden text_area, whose value only reaches the backend reliably when
        # a form submit commits all pending widget values. A plain st.button
        # reads a stale value and silently loses note edits. Keeping all the
        # other inputs in the same form also avoids intermediate reruns that
        # would remount the editor iframe while the user is typing.
        with st.form(f"task_edit_{task['id']}", border=False):
            new_name = st.text_input(
                "Task name",
                value=curr_name,
                key=f"task_name_{task.get('id')}",
            )
            st.html(pills_html)
            st.markdown("---")

            # ── Row 1: Status | Priority | Deliverable ────────────────────────
            c1, c2, c3 = st.columns(3)
            with c1:
                new_status_display = st.selectbox(
                    "Status", display_options,
                    index=status_options.index(curr_status)
                )
            with c2:
                priority_options = ["none", "low", "medium", "high", "urgent"]
                curr_priority = task.get("priority", "medium")
                if curr_priority not in priority_options:
                    curr_priority = "medium"
                new_priority = st.selectbox(
                    "Priority", priority_options,
                    index=priority_options.index(curr_priority)
                )
            with c3:
                new_deliv_name = st.selectbox(
                    "Deliverable",
                    list(deliv_opts.keys()),
                    index=list(deliv_opts.keys()).index(curr_deliv_name)
                )

            # ── Row 2: Assignee | Supervisor | Deadline ───────────────────────
            c4, c5, c6 = st.columns([2, 2, 1])
            with c4:
                if _is_admin_modal:
                    new_owner_disp = st.selectbox("Assignee", owner_keys, index=owner_idx)
                else:
                    st.caption("Assignee")
                    st.write(curr_owner_disp or task.get("owner_email") or "—")
                    new_owner_disp = None
            with c5:
                if _is_admin_modal:
                    new_sup_disp = st.selectbox("Supervisor", sup_keys, index=sup_idx)
                else:
                    st.caption("Supervisor")
                    st.write(curr_sup_disp if curr_sup_disp != "None" else "—")
                    new_sup_disp = None
            with c6:
                new_deadline = st.date_input("Deadline", value=curr_deadline, format="DD/MM/YYYY")

            # ── Markdown notes editor ─────────────────────────────────────────
            new_notes = markdown_editor(
                value=task.get("notes") or "",
                key=f"task_notes_{task['id']}",
                height=340,
                label="📝 Notes / Description",
            )

            st.markdown("---")

            c_save, c_empty, c_arch = st.columns([2, 2, 2])
            with c_save:
                submitted = st.form_submit_button(
                    "💾 Save Changes", type="primary", use_container_width=True
                )

        new_status = status_options[display_options.index(new_status_display)]
        new_deliv_id = deliv_opts[new_deliv_name]
        if _is_admin_modal:
            new_owner_email = user_opts.get(new_owner_disp) or task.get("owner_email")
            new_sup_email = user_opts.get(new_sup_disp) if new_sup_disp != "None" else None
        else:
            new_owner_email = task.get("owner_email")
            new_sup_email = task.get("supervisor_email")

        if submitted:
            try:
                if not (new_name or "").strip():
                    st.error("Task name is required.")
                    return
                update_data = {
                    "name":             (new_name or "").strip(),
                    "notes":            new_notes,
                    "status":           new_status,
                    "priority":         new_priority,
                    "deliverable_id":   new_deliv_id,
                    "owner_email":      new_owner_email,
                    "supervisor_email": new_sup_email,
                    "deadline":         new_deadline.isoformat() if new_deadline else None,
                }

                # Auto-manage completion date
                if new_status == "Completed" and curr_status != "Completed":
                    update_data["completion_date"] = datetime.datetime.now().date().isoformat()
                elif new_status != "Completed" and curr_status == "Completed":
                    update_data["completion_date"] = None

                # Only write fields that actually changed: avoids clobbering
                # concurrent edits by another user holding a stale snapshot.
                changed = {k: v for k, v in update_data.items() if task.get(k) != v}
                if not changed:
                    st.info("No changes to save.")
                    return

                res = supabase.table("tasks").update(changed).eq("id", task["id"]).execute()
                if not getattr(res, "data", None):
                    st.error("Save failed: the database did not confirm the update.")
                    return

                if "status" in changed:
                    log_status_change(
                        "task", task["id"], task.get("project_id"),
                        task.get("status"), new_status,
                        st.session_state.get("user_email"),
                    )

                # Notify on assignment changes
                assigner = st.session_state.get("user_name", st.session_state.get("user_email", ""))
                enriched = {**task, **update_data}
                old_owner = task.get("owner_email")
                old_sup   = task.get("supervisor_email")
                if new_owner_email and new_owner_email != old_owner:
                    send_task_assigned(enriched, new_owner_email, assigner)
                if new_sup_email and new_sup_email != old_sup and new_sup_email != new_owner_email:
                    send_task_assigned(enriched, new_sup_email, assigner)

                st.success("Saved!")
                _mde_key = f"task_notes_{task['id']}"
                st.session_state.pop(f"__mde_{_mde_key}", None)
                st.session_state.pop(f"{_mde_key}_ta", None)
                st.rerun()
            except Exception as e:
                st.error(f"Error: {e}")

        c_a1, c_a2, c_a3 = st.columns([2, 2, 2])
        with c_a3:
            if st.button("🗑️ Archive Task", use_container_width=True):
                try:
                    supabase.table("tasks").update({"is_archived": True}).eq("id", task["id"]).execute()
                    st.rerun()
                except Exception as e:
                    st.error(f"Error: {e}")
    else:
        # ── Read-only view ────────────────────────────────────────────────────
        st.html(f"<div style='font-size:1.15rem;font-weight:700;margin-bottom:4px'>{curr_name}</div>")
        st.html(pills_html)
        st.markdown("---")
        st.write(f"**Status**: {status_map.get(task.get('status', 'Not started'))}")
        st.write(f"**Priority**: {render_priority_badge(task.get('priority'))}")
        if task.get("deadline"):
            st.write(f"**Deadline**: {_fmt_date(task.get('deadline'))}")
        if task.get("completion_date"):
            st.write(f"**Completed on**: {_fmt_date(task.get('completion_date'))}")
        st.write("**Notes/Description**:")
        st.markdown(task.get("notes") or "*No notes provided.*")

    # ── Comments thread (shown in both edit and read-only modes) ──────────────
    _render_task_comments(task, can_edit=can_edit, project_name=proj.get("name"))


@st.dialog("Subtask Details", width="large")
def subtask_details_modal(subtask, can_edit):
    # ── Header: breadcrumb → name → persons ──────────────────────────────────
    parent, proj, deliv, user_map = _fetch_subtask_ctx(subtask)
    seq_id = subtask.get("sequence_id") or f"S-{subtask.get('id')}"
    st.html(_breadcrumb_html(seq_id=seq_id, proj=proj, deliv=deliv, parent_task=parent or None))

    curr_name = subtask.get("name", "") or ""
    pills_html = _persons_pills_html(
        user_map=user_map,
        owner_email=subtask.get("owner_email"),
        sup_email=subtask.get("supervisor_email"),
    )
    status_map = get_status_color_map()

    if can_edit:
        # ── Fetch supporting data ─────────────────────────────────────────────
        all_users = _fetch_all_users()
        user_opts = _user_opts(all_users)

        status_options = list(status_map.keys())
        display_options = list(status_map.values())

        curr_status = subtask.get("status") or "Not started"
        if curr_status not in status_options:
            curr_status = "Not started"

        owner_keys = list(user_opts.keys())
        curr_owner_disp = _find_display(user_opts, subtask.get("owner_email"))
        owner_idx = owner_keys.index(curr_owner_disp) if curr_owner_disp in owner_keys else 0

        sup_keys = ["None"] + owner_keys
        curr_sup_disp = _find_display(user_opts, subtask.get("supervisor_email")) or "None"
        sup_idx = sup_keys.index(curr_sup_disp) if curr_sup_disp in sup_keys else 0

        curr_deadline = _parse_date(subtask.get("deadline"))

        # Admins can reassign; non-admin owners/supervisors keep current assignment
        _is_admin_modal = st.session_state.get("user_role") == "admin"

        # ── Edit form ─────────────────────────────────────────────────────────
        # Same rationale as task_details_modal: the form submit is what
        # reliably commits the hidden markdown-editor sink textarea, and it
        # prevents intermediate reruns from remounting the editor iframe.
        with st.form(f"subtask_edit_{subtask['id']}", border=False):
            new_name = st.text_input(
                "Subtask name",
                value=curr_name,
                key=f"subtask_name_{subtask.get('id')}",
            )
            st.html(pills_html)
            st.markdown("---")

            # ── Row 1: Status ─────────────────────────────────────────────────
            new_status_display = st.selectbox(
                "Status", display_options,
                index=status_options.index(curr_status)
            )

            # ── Row 2: Assignee | Supervisor | Deadline ───────────────────────
            c1, c2, c3 = st.columns([2, 2, 1])
            with c1:
                if _is_admin_modal:
                    new_owner_disp = st.selectbox("Assignee", owner_keys, index=owner_idx)
                else:
                    st.caption("Assignee")
                    st.write(curr_owner_disp or subtask.get("owner_email") or "—")
                    new_owner_disp = None
            with c2:
                if _is_admin_modal:
                    new_sup_disp = st.selectbox("Supervisor", sup_keys, index=sup_idx)
                else:
                    st.caption("Supervisor")
                    st.write(curr_sup_disp if curr_sup_disp != "None" else "—")
                    new_sup_disp = None
            with c3:
                new_deadline = st.date_input("Deadline", value=curr_deadline, format="DD/MM/YYYY")

            # ── Markdown notes editor ─────────────────────────────────────────
            new_notes = markdown_editor(
                value=subtask.get("notes") or "",
                key=f"subtask_notes_{subtask['id']}",
                height=300,
                label="📝 Notes / Description",
            )

            st.markdown("---")

            c_save, c_empty, c_arch = st.columns([2, 2, 2])
            with c_save:
                submitted = st.form_submit_button(
                    "💾 Save Changes", type="primary", use_container_width=True
                )

        new_status = status_options[display_options.index(new_status_display)]
        if _is_admin_modal:
            new_owner_email = user_opts.get(new_owner_disp) or subtask.get("owner_email")
            new_sup_email = user_opts.get(new_sup_disp) if new_sup_disp != "None" else None
        else:
            new_owner_email = subtask.get("owner_email")
            new_sup_email = subtask.get("supervisor_email")

        if submitted:
            try:
                if not (new_name or "").strip():
                    st.error("Subtask name is required.")
                    return
                update_data = {
                    "name":             (new_name or "").strip(),
                    "notes":            new_notes,
                    "status":           new_status,
                    "owner_email":      new_owner_email,
                    "supervisor_email": new_sup_email,
                    "deadline":         new_deadline.isoformat() if new_deadline else None,
                }

                # Only write fields that actually changed: avoids clobbering
                # concurrent edits by another user holding a stale snapshot.
                changed = {k: v for k, v in update_data.items() if subtask.get(k) != v}
                if not changed:
                    st.info("No changes to save.")
                    return

                res = supabase.table("subtasks").update(changed).eq("id", subtask["id"]).execute()
                if not getattr(res, "data", None):
                    st.error("Save failed: the database did not confirm the update.")
                    return

                if "status" in changed:
                    log_status_change(
                        "subtask", subtask["id"], (parent or {}).get("project_id"),
                        subtask.get("status"), new_status,
                        st.session_state.get("user_email"),
                    )

                # Notify on assignment changes
                assigner = st.session_state.get("user_name", st.session_state.get("user_email", ""))
                enriched = {**subtask, **update_data}
                old_owner = subtask.get("owner_email")
                old_sup   = subtask.get("supervisor_email")
                if new_owner_email and new_owner_email != old_owner:
                    send_task_assigned(enriched, new_owner_email, assigner)
                if new_sup_email and new_sup_email != old_sup and new_sup_email != new_owner_email:
                    send_task_assigned(enriched, new_sup_email, assigner)

                st.success("Saved!")
                _mde_key = f"subtask_notes_{subtask['id']}"
                st.session_state.pop(f"__mde_{_mde_key}", None)
                st.session_state.pop(f"{_mde_key}_ta", None)
                st.rerun()
            except Exception as e:
                st.error(f"Error: {e}")

        c_a1, c_a2, c_a3 = st.columns([2, 2, 2])
        with c_a3:
            if st.button("🗑️ Archive Subtask", key="arch_st", use_container_width=True):
                try:
                    supabase.table("subtasks").update({"is_archived": True}).eq("id", subtask["id"]).execute()
                    st.rerun()
                except Exception as e:
                    st.error(f"Error: {e}")
    else:
        # ── Read-only view ────────────────────────────────────────────────────
        st.html(f"<div style='font-size:1.15rem;font-weight:700;margin-bottom:4px'>{curr_name}</div>")
        st.html(pills_html)
        st.markdown("---")
        st.write(f"**Status**: {status_map.get(subtask.get('status', 'Not started'))}")
        if subtask.get("deadline"):
            st.write(f"**Deadline**: {_fmt_date(subtask.get('deadline'))}")
        st.write("**Notes/Description**:")
        st.markdown(subtask.get("notes") or "*No notes provided.*")


# ── Deliverable Details Modal ─────────────────────────────────────────────────

@st.dialog("Deliverable Details", width="large")
def deliverable_details_modal(deliverable: dict, can_edit: bool = False, breadcrumb: str | None = None):
    """Show deliverable details with an optional edit form for admins."""
    from utils.md_editor import markdown_editor as _md_editor

    d_id     = deliverable.get("id")
    d_name   = deliverable.get("name", "")
    d_type   = deliverable.get("type", "")
    d_status = deliverable.get("status", "Not started")
    d_dead   = deliverable.get("deadline")
    d_desc   = deliverable.get("description") or ""
    d_owner  = deliverable.get("owner_email")
    d_sup    = deliverable.get("supervisor_email")

    users_rows = supabase.table("users").select("email, name").eq("is_approved", True).order("name").execute().data
    users_map = {u["email"]: u.get("name", u["email"]) for u in (users_rows or [])}

    STATUS_OPTS = ["Not started", "Working on", "Blocked", "Completed", "Cancelled"]
    cfg = get_settings()
    TYPE_OPTS = [
        s["name"].strip()
        for s in parse_deliverable_tag_styles(cfg.get("deliverable_tag_styles"), fallback_to_default=False)
        if str(s.get("name", "")).strip()
    ]
    if not TYPE_OPTS:
        raw_types = cfg.get("deliverable_types")
        if isinstance(raw_types, str):
            try:
                parsed = json.loads(raw_types)
                if isinstance(parsed, list):
                    TYPE_OPTS = [str(v).strip() for v in parsed if str(v).strip()]
            except Exception:
                TYPE_OPTS = []
    if not TYPE_OPTS:
        TYPE_OPTS = ["paper", "layout", "prototype"]
    _SC = {
        "Not started": ("#888888", "#f0f0f0"),
        "Working on":  ("#1565C0", "#E3F2FD"),
        "Blocked":     ("#E65100", "#FFF3E0"),
        "Completed":   ("#2E7D32", "#E8F5E9"),
        "Cancelled":   ("#B71C1C", "#FFEBEE"),
    }
    s_fg, s_bg = _SC.get(d_status, ("#888", "#f0f0f0"))

    # ── Read-only header ──────────────────────────────────────────────────────
    if breadcrumb:
        st.caption(breadcrumb)
    st.html(f"<span style='font-size:1.2rem;font-weight:700'>{d_name}</span>")
    m1, m2, m3, m4, m5 = st.columns(5)
    with m1:
        st.caption("Status")
        st.html(
            f"<span style='background:{s_bg};color:{s_fg};padding:3px 10px;"
            f"border-radius:4px;font-weight:600;font-size:0.88rem'>{d_status}</span>"
        )
    with m2:
        st.caption("Type")
        st.write(d_type or "—")
    with m3:
        st.caption("Deadline")
        st.write(_fmt_date(d_dead))
    with m4:
        st.caption("Owner")
        st.write(users_map.get(d_owner, d_owner) if d_owner else "—")
    with m5:
        st.caption("Supervisor")
        st.write(users_map.get(d_sup, d_sup) if d_sup else "—")

    pills = ""
    if d_owner:
        u = next((u for u in (users_rows or []) if u.get("email") == d_owner), None) or {
            "name": d_owner,
            "avatar_color": "#534AB7",
        }
        pills += person_pill_html(
            u.get("name", d_owner),
            u.get("avatar_color", "#534AB7"),
            role="owner",
            compact=False,
        )
    if d_sup and d_sup != d_owner:
        u = next((u for u in (users_rows or []) if u.get("email") == d_sup), None) or {
            "name": d_sup,
            "avatar_color": "#BA7517",
        }
        pills += person_pill_html(
            u.get("name", d_sup),
            u.get("avatar_color", "#BA7517"),
            role="sup",
            compact=False,
        )
    if pills:
        st.html(f"<div style='margin:8px 0'>{pills}</div>")

    if d_desc and not can_edit:
        st.divider()
        st.caption("Description")
        st.markdown(d_desc)
    elif not d_desc and not can_edit:
        st.caption("No description provided.")

    if not can_edit:
        return

    # ── Edit form ─────────────────────────────────────────────────────────────
    st.divider()
    with st.form("edit_deliv_form"):
        ef1, ef2 = st.columns(2)
        with ef1:
            e_name = st.text_input("Name*", value=d_name)
            e_type = st.selectbox(
                "Type", TYPE_OPTS,
                index=TYPE_OPTS.index(d_type) if d_type in TYPE_OPTS else 0
            )
        with ef2:
            e_status = st.selectbox(
                "Status", STATUS_OPTS,
                index=STATUS_OPTS.index(d_status) if d_status in STATUS_OPTS else 0
            )
            e_dead = st.date_input("Deadline", value=_parse_date(d_dead), format="DD/MM/YYYY")

        owner_opts = {f"{u.get('name', u['email'])} ({u['email']})": u["email"] for u in (users_rows or [])}
        owner_labels = list(owner_opts.keys())
        default_owner_idx = 0
        if d_owner:
            for i, lab in enumerate(owner_labels):
                if owner_opts[lab] == d_owner:
                    default_owner_idx = i
                    break
        e_owner_label = st.selectbox("Owner", owner_labels, index=default_owner_idx)

        sup_opts = {"None": None}
        sup_opts.update({f"{u.get('name', u['email'])} ({u['email']})": u["email"] for u in (users_rows or [])})
        sup_labels = list(sup_opts.keys())
        default_sup_idx = 0
        if d_sup:
            for i, lab in enumerate(sup_labels):
                if sup_opts[lab] == d_sup:
                    default_sup_idx = i
                    break
        e_sup_label = st.selectbox("Supervisor", sup_labels, index=default_sup_idx)
        e_desc = _md_editor(
            value=d_desc,
            key=f"deliv_desc_{d_id}",
            height=220,
            label="📝 Description (Markdown)",
        )
        if st.form_submit_button("💾 Save Changes", type="primary"):
            if not e_name:
                st.error("Name is required.")
                return
            try:
                supabase.table("deliverables").update({
                    "name":        e_name,
                    "type":        e_type,
                    "status":      e_status,
                    "deadline":    e_dead.isoformat() if e_dead else None,
                    "owner_email": owner_opts[e_owner_label],
                    "supervisor_email": sup_opts[e_sup_label],
                    "description": e_desc or None,
                }).eq("id", d_id).execute()
                st.success("Saved!")
                st.rerun()
            except Exception as ex:
                st.error(f"Error: {ex}")
