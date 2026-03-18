"""views/admin.py — MAIC LAB Admin Panel.

Accessible only to users with role 'admin'.
Tabs: Users | Projects | Archive | Settings & Notifications
"""

import streamlit as st
import datetime
from core.supabase_client import supabase
from db import (
    get_archived_projects, get_archived_deliverables,
    get_archived_tasks, get_archived_subtasks,
    delete_task_cascade, delete_deliverable_cascade, delete_project_cascade,
    get_settings, save_settings, SETTINGS_MIGRATION_SQL, DELIVERABLES_MIGRATION_SQL,
    PROJECTS_MIGRATION_SQL,
)
from utils.md_editor import markdown_editor


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _fmt_date(d: str | None) -> str:
    if not d:
        return "—"
    try:
        return datetime.date.fromisoformat(d).strftime("%Y/%m/%d")
    except Exception:
        return d or "—"


def _parse_date(value: str | None) -> datetime.date | None:
    if not value:
        return None
    try:
        return datetime.date.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def _projects_map() -> dict:
    rows = supabase.table("projects").select("id, name").execute().data
    return {r["id"]: r["name"] for r in rows}


def _deliverables_map() -> dict:
    rows = supabase.table("deliverables").select("id, name, project_id").execute().data
    return {r["id"]: r for r in rows}


def _project_markdown_export(projects: list[dict]) -> str:
    lines = ["# Project List", ""]
    for proj in projects:
        title = proj.get("name") or "Unnamed project"
        acronym = proj.get("acronym")
        if acronym:
            title = f"{title} ({acronym})"
        lines.append(f"## {title}")

        details = []
        if proj.get("identifier"):
            details.append(f"- Identifier: {proj['identifier']}")
        if proj.get("funding_agency"):
            details.append(f"- Funding agency: {proj['funding_agency']}")
        if proj.get("start_date"):
            details.append(f"- Start date: {_fmt_date(proj['start_date'])}")
        if proj.get("end_date"):
            details.append(f"- End date: {_fmt_date(proj['end_date'])}")
        if details:
            lines.extend(details)

        description = (proj.get("description") or "").strip()
        if description:
            lines.extend(["", description])

        lines.append("")
    return "\n".join(lines).strip() + "\n"


# ─── TAB 1: Users ─────────────────────────────────────────────────────────────

def _tab_users():
    st.subheader("System Users")

    try:
        users = supabase.table("users").select("*").order("name").execute().data
    except Exception as e:
        st.error(f"Error loading users: {e}")
        return

    if not users:
        st.info("No users found.")
    else:
        hc1, hc2, hc3, hc4, hc5, hc6, hc7, hc8 = st.columns([2, 2.5, 1.2, 1.2, 1.3, 1.3, 1.2, 1.2])
        hc1.markdown("**Name**")
        hc2.markdown("**Email**")
        hc3.markdown("**Role**")
        hc4.markdown("**Status**")
        hc5.markdown("**Toggle Role**")
        hc6.markdown("**Activate**")
        hc7.markdown("**Edit**")
        hc8.markdown("**Delete**")
        st.divider()

        for u in users:
            email        = u["email"]
            name         = u.get("name", email)
            role         = u.get("role", "user")
            approved     = u.get("is_approved", False)
            status_label = "Active" if approved else "Inactive"
            status_icon  = "🟢" if approved else "🔴"
            # Use email-safe session state keys
            safe_key     = email.replace("@", "_at_").replace(".", "_")
            edit_key     = f"_edit_user_{safe_key}"
            del_key      = f"_del_user_{safe_key}"

            c1, c2, c3, c4, c5, c6, c7, c8 = st.columns([2, 2.5, 1.2, 1.2, 1.3, 1.3, 1.2, 1.2])
            c1.write(name)
            c2.write(email)
            c3.write(role.capitalize())
            c4.write(f"{status_icon} {status_label}")

            with c5:
                new_role = "user" if role == "admin" else "admin"
                if st.button(f"→ {new_role}", key=f"role_{safe_key}", use_container_width=True):
                    supabase.table("users").update({"role": new_role}).eq("email", email).execute()
                    st.rerun()

            with c6:
                if approved:
                    if st.button("Deactivate", key=f"deact_{safe_key}", use_container_width=True):
                        supabase.table("users").update({"is_approved": False}).eq("email", email).execute()
                        st.rerun()
                else:
                    if st.button("Reactivate", key=f"react_{safe_key}", use_container_width=True):
                        supabase.table("users").update({"is_approved": True}).eq("email", email).execute()
                        st.rerun()

            with c7:
                if st.button("✏️ Edit", key=f"edit_btn_{safe_key}", use_container_width=True):
                    st.session_state[edit_key] = not st.session_state.get(edit_key, False)
                    st.session_state.pop(del_key, None)
                    st.rerun()

            with c8:
                if st.button("✕ Delete", key=f"del_btn_{safe_key}", use_container_width=True):
                    st.session_state[del_key] = not st.session_state.get(del_key, False)
                    st.session_state.pop(edit_key, None)
                    st.rerun()

            # ── Inline edit form ───────────────────────────────────────────
            if st.session_state.get(edit_key):
                with st.container(border=True):
                    st.caption(f"Editing: **{name}**")
                    ef1, ef2 = st.columns(2)
                    with ef1:
                        e_name  = st.text_input("Full Name*", value=name,  key=f"e_name_{safe_key}")
                        e_email = st.text_input("Email*",     value=email, key=f"e_email_{safe_key}")
                    with ef2:
                        e_role  = st.selectbox(
                            "Role", ["user", "admin"],
                            index=["user", "admin"].index(role) if role in ["user", "admin"] else 0,
                            key=f"e_role_{safe_key}",
                        )
                        e_color = st.color_picker(
                            "Avatar Color",
                            value=u.get("avatar_color") or "#888888",
                            key=f"e_color_{safe_key}",
                        )
                    sb1, sb2 = st.columns(2)
                    with sb1:
                        if st.button("💾 Save", key=f"save_user_{safe_key}",
                                     type="primary", use_container_width=True):
                            if not e_name or not e_email:
                                st.error("Name and email are required.")
                            else:
                                try:
                                    supabase.table("users").update({
                                        "name":         e_name,
                                        "email":        e_email,
                                        "role":         e_role,
                                        "avatar_color": e_color,
                                    }).eq("email", email).execute()
                                    st.session_state.pop(edit_key, None)
                                    st.success("User updated.")
                                    st.rerun()
                                except Exception as ex:
                                    st.error(f"Error: {ex}")
                    with sb2:
                        if st.button("Cancel", key=f"cancel_edit_{safe_key}", use_container_width=True):
                            st.session_state.pop(edit_key, None)
                            st.rerun()

            # ── Inline delete confirmation ────────────────────────────────
            if st.session_state.get(del_key):
                st.warning(
                    f"⚠️ Permanently delete **{name}** ({email})? "
                    "This action cannot be undone."
                )
                dy, dn = st.columns(2)
                with dy:
                    if st.button("Yes, delete", key=f"yes_del_{safe_key}",
                                 type="primary", use_container_width=True):
                        try:
                            supabase.table("users").delete().eq("email", email).execute()
                            st.session_state.pop(del_key, None)
                            st.rerun()
                        except Exception as ex:
                            st.error(f"Error: {ex}")
                with dn:
                    if st.button("Cancel", key=f"no_del_{safe_key}", use_container_width=True):
                        st.session_state.pop(del_key, None)
                        st.rerun()

    st.divider()

    # ── Add new user ───────────────────────────────────────────────────────
    st.subheader("Add New User")
    with st.form("add_user_form", clear_on_submit=True):
        f1, f2, f3 = st.columns([2, 2.5, 1.5])
        with f1:
            new_name = st.text_input("Full Name*")
        with f2:
            new_email = st.text_input("Email*")
        with f3:
            new_role_sel = st.selectbox("Role", ["user", "admin"])

        submitted = st.form_submit_button("Add User", type="primary")
        if submitted:
            if not new_name or not new_email:
                st.error("Name and email are required.")
            else:
                existing = supabase.table("users").select("email").eq("email", new_email).execute().data
                if existing:
                    st.error(f"Email {new_email} is already registered.")
                else:
                    try:
                        supabase.table("users").insert({
                            "email":        new_email,
                            "name":         new_name,
                            "role":         new_role_sel,
                            "is_approved":  True,
                            "avatar_color": "#{:06x}".format(abs(hash(new_email)) % 0xFFFFFF),
                        }).execute()
                        st.success(f"User {new_name} added.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {e}")


# ─── TAB 2: Projects ──────────────────────────────────────────────────────────

def _tab_projects():
    st.subheader("Project List")
    st.caption("Manage all active projects. Archived projects are in the Archive tab.")

    try:
        projects = (
            supabase.table("projects")
            .select("*")
            .eq("is_archived", False)
            .order("name")
            .execute()
            .data
        )
    except Exception as e:
        st.error(f"Error loading projects: {e}")
        return

    export_md = _project_markdown_export(projects)
    st.download_button(
        "⬇ Export project list (Markdown)",
        data=export_md,
        file_name="project_list.md",
        mime="text/markdown",
        use_container_width=True,
    )

    if not projects:
        st.info("No active projects found.")
    else:
        for proj in projects:
            pid        = proj["id"]
            pname      = proj.get("name", "?")
            acronym    = proj.get("acronym") or ""
            identifier = proj.get("identifier") or ""
            funding    = proj.get("funding_agency") or ""
            edit_key   = f"_edit_proj_{pid}"
            del_key    = f"_del_proj_{pid}"

            with st.container(border=True):
                ci, ca, cd = st.columns([6, 1.2, 1.2])
                with ci:
                    label = f"**{acronym}** — {pname}" if acronym else f"**{pname}**"
                    st.markdown(label)
                    meta_parts = []
                    if identifier:
                        meta_parts.append(f"ID: {identifier}")
                    if funding:
                        meta_parts.append(f"Funding: {funding}")
                    start_d = proj.get("start_date")
                    end_d   = proj.get("end_date")
                    if start_d or end_d:
                        meta_parts.append(f"{_fmt_date(start_d)} → {_fmt_date(end_d)}")
                    if meta_parts:
                        st.caption("  ·  ".join(meta_parts))
                    description = (proj.get("description") or "").strip()
                    if description:
                        st.markdown(description)

                with ca:
                    if st.button("✏️ Edit", key=f"edit_proj_{pid}", use_container_width=True):
                        st.session_state[edit_key] = not st.session_state.get(edit_key, False)
                        st.session_state.pop(del_key, None)
                        st.rerun()

                with cd:
                    if st.button("✕ Delete", key=f"del_proj_{pid}", use_container_width=True):
                        st.session_state[del_key] = not st.session_state.get(del_key, False)
                        st.session_state.pop(edit_key, None)
                        st.rerun()

                # ── Inline edit form ──────────────────────────────────────
                if st.session_state.get(edit_key):
                    st.markdown("---")
                    pf1, pf2 = st.columns(2)
                    with pf1:
                        p_name    = st.text_input("Project Name*", value=pname,      key=f"p_name_{pid}")
                        p_acronym = st.text_input("Acronym",       value=acronym,    key=f"p_acro_{pid}")
                        p_idf     = st.text_input("Identifier",    value=identifier, key=f"p_idf_{pid}")
                    with pf2:
                        p_funding = st.text_input("Funding Agency", value=funding, key=f"p_fund_{pid}")
                        p_start   = st.date_input(
                            "Start Date",
                            value=_parse_date(proj.get("start_date")),
                            format="DD/MM/YYYY",
                            key=f"p_start_{pid}",
                        )
                        p_end = st.date_input(
                            "End Date",
                            value=_parse_date(proj.get("end_date")),
                            format="DD/MM/YYYY",
                            key=f"p_end_{pid}",
                        )
                    p_description = markdown_editor(
                        value=proj.get("description") or "",
                        key=f"edit_proj_notes_{pid}",
                        height=220,
                        label="📝 Project Description (optional)",
                    )
                    pb1, pb2 = st.columns(2)
                    with pb1:
                        if st.button("💾 Save", key=f"save_proj_{pid}",
                                     type="primary", use_container_width=True):
                            if not p_name:
                                st.error("Project name is required.")
                            else:
                                try:
                                    supabase.table("projects").update({
                                        "name":           p_name,
                                        "acronym":        p_acronym or None,
                                        "identifier":     p_idf     or None,
                                        "funding_agency": p_funding or None,
                                        "start_date":     p_start.isoformat() if p_start else None,
                                        "end_date":       p_end.isoformat()   if p_end   else None,
                                        "description":    p_description.strip() or None,
                                    }).eq("id", pid).execute()
                                    st.session_state.pop(edit_key, None)
                                    st.success("Project updated.")
                                    st.rerun()
                                except Exception as ex:
                                    st.error(f"Error: {ex}")
                    with pb2:
                        if st.button("Cancel", key=f"cancel_proj_{pid}", use_container_width=True):
                            st.session_state.pop(edit_key, None)
                            st.rerun()

                # ── Inline delete confirmation ────────────────────────────
                if st.session_state.get(del_key):
                    st.warning(
                        f"⚠️ Permanently delete **{pname}** and ALL its deliverables and tasks? "
                        "This action cannot be undone."
                    )
                    dy, dn = st.columns(2)
                    with dy:
                        if st.button("Yes, delete", key=f"yes_proj_{pid}",
                                     type="primary", use_container_width=True):
                            try:
                                delete_project_cascade(pid)
                                st.session_state.pop(del_key, None)
                                st.rerun()
                            except Exception as ex:
                                st.error(f"Error: {ex}")
                    with dn:
                        if st.button("Cancel", key=f"no_proj_{pid}", use_container_width=True):
                            st.session_state.pop(del_key, None)
                            st.rerun()

    st.divider()

    # ── Add new project ────────────────────────────────────────────────────
    st.subheader("Add New Project")
    with st.form("add_project_form", clear_on_submit=True):
        af1, af2 = st.columns(2)
        with af1:
            np_name    = st.text_input("Project Name*")
            np_acronym = st.text_input("Acronym")
            np_idf     = st.text_input("Identifier")
        with af2:
            np_funding = st.text_input("Funding Agency")
            np_start   = st.date_input("Start Date", value=None, format="DD/MM/YYYY")
            np_end     = st.date_input("End Date",   value=None, format="DD/MM/YYYY")
        np_description = markdown_editor(
            value="",
            key="admin_new_proj_notes",
            height=220,
            label="📝 Project Description (optional)",
        )

        add_btn = st.form_submit_button("➕ Add Project", type="primary")
        if add_btn:
            if not np_name:
                st.error("Project name is required.")
            else:
                try:
                    supabase.table("projects").insert({
                        "name":           np_name,
                        "acronym":        np_acronym or None,
                        "identifier":     np_idf     or None,
                        "funding_agency": np_funding or None,
                        "start_date":     np_start.isoformat() if np_start else None,
                        "end_date":       np_end.isoformat()   if np_end   else None,
                        "description":    np_description.strip() or None,
                        "is_archived":    False,
                    }).execute()
                    # clear admin new-project description editor
                    st.session_state.pop("__mde_admin_new_proj_notes", None)
                    st.success(f"Project '{np_name}' created.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error: {e}")


# ─── TAB 3: Archive ───────────────────────────────────────────────────────────

def _confirm_key(record_type: str, record_id) -> str:
    return f"confirm_delete_{record_type}_{record_id}"


def _archive_section(label: str, records: list, record_type: str,
                     restore_fn, delete_fn, name_fn, parent_fn):
    count = len(records)
    with st.expander(f"{label} ({count})", expanded=False):
        if not records:
            st.caption("No archived records.")
            return
        for r in records:
            rid     = r["id"]
            rname   = name_fn(r)
            parent  = parent_fn(r)
            updated = _fmt_date(r.get("updated_at") or r.get("deadline"))
            ck      = _confirm_key(record_type, rid)

            with st.container(border=True):
                col_info, col_restore, col_delete = st.columns([5, 1.5, 1.5])
                with col_info:
                    st.write(f"**{rname}**")
                    if parent:
                        st.caption(f"Project: {parent}  ·  last modified: {updated}")
                    else:
                        st.caption(f"Last modified: {updated}")

                with col_restore:
                    if st.button("↩ Restore", key=f"restore_{record_type}_{rid}",
                                 use_container_width=True):
                        restore_fn(rid)
                        st.success(f"'{rname}' restored.")
                        st.rerun()

                with col_delete:
                    if st.button("🗑 Delete", key=f"del_{record_type}_{rid}",
                                 use_container_width=True, type="secondary"):
                        st.session_state[ck] = True

                if st.session_state.get(ck):
                    st.warning(
                        f"⚠️ This action is irreversible. "
                        f"Confirm deletion of **{rname}**?"
                    )
                    yes_col, no_col = st.columns(2)
                    with yes_col:
                        if st.button("Yes, delete", key=f"yes_{record_type}_{rid}",
                                     type="primary", use_container_width=True):
                            try:
                                delete_fn(rid)
                                st.success(f"'{rname}' permanently deleted.")
                                del st.session_state[ck]
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error: {e}")
                    with no_col:
                        if st.button("Cancel", key=f"no_{record_type}_{rid}",
                                     use_container_width=True):
                            del st.session_state[ck]
                            st.rerun()


def _tab_archive():
    st.subheader("Archive")
    st.caption("All archived records. Restore or permanently delete.")

    proj_map  = _projects_map()
    deliv_map = _deliverables_map()

    # ── Bulk actions for tasks ────────────────────────────────────────────────
    c1, c2 = st.columns(2)
    with c1:
        if st.button("🗑 Delete ALL archived tasks", key="bulk_del_arch_tasks", use_container_width=True):
            st.session_state["_confirm_bulk_del_arch_tasks"] = True
    with c2:
        if st.button("📦 Archive ALL completed tasks", key="bulk_arch_completed_tasks", use_container_width=True):
            st.session_state["_confirm_bulk_arch_completed_tasks"] = True

    # Confirm delete all archived tasks
    if st.session_state.get("_confirm_bulk_del_arch_tasks"):
        st.warning(
            "⚠️ This will permanently delete **all archived tasks** and their related subtasks, "
            "comments, labels and dependencies. This action cannot be undone."
        )
        dc1, dc2 = st.columns(2)
        with dc1:
            if st.button("Yes, delete all archived tasks", key="yes_bulk_del_arch_tasks", type="primary", use_container_width=True):
                try:
                    arch_tasks_all = get_archived_tasks() or []
                    for t in arch_tasks_all:
                        delete_task_cascade(t["id"])
                    st.success(f"Deleted {len(arch_tasks_all)} archived tasks.")
                except Exception as e:
                    st.error(f"Error during bulk delete: {e}")
                finally:
                    st.session_state.pop("_confirm_bulk_del_arch_tasks", None)
                    st.rerun()
        with dc2:
            if st.button("Cancel", key="no_bulk_del_arch_tasks", use_container_width=True):
                st.session_state.pop("_confirm_bulk_del_arch_tasks", None)
                st.rerun()

    # Confirm archive all completed tasks
    if st.session_state.get("_confirm_bulk_arch_completed_tasks"):
        st.warning(
            "Archive **all tasks with status 'Completed'** (they will move to the Archived Tasks section). "
            "This does not delete data; it only sets is_archived = true."
        )
        ac1, ac2 = st.columns(2)
        with ac1:
            if st.button("Yes, archive completed tasks", key="yes_bulk_arch_completed_tasks", type="primary", use_container_width=True):
                try:
                    supabase.table("tasks").update({"is_archived": True}).eq("status", "Completed").eq("is_archived", False).execute()
                    st.success("All completed tasks have been archived.")
                except Exception as e:
                    st.error(f"Error during bulk archive: {e}")
                finally:
                    st.session_state.pop("_confirm_bulk_arch_completed_tasks", None)
                    st.rerun()
        with ac2:
            if st.button("Cancel", key="no_bulk_arch_completed_tasks", use_container_width=True):
                st.session_state.pop("_confirm_bulk_arch_completed_tasks", None)
                st.rerun()

    arch_projs = get_archived_projects()
    _archive_section(
        label="Archived Projects",
        records=arch_projs,
        record_type="project",
        restore_fn=lambda rid: supabase.table("projects").update({"is_archived": False}).eq("id", rid).execute(),
        delete_fn=delete_project_cascade,
        name_fn=lambda r: f"{r.get('name', '?')} ({r.get('acronym', '')})",
        parent_fn=lambda r: "",
    )

    arch_delivs = get_archived_deliverables()
    _archive_section(
        label="Archived Deliverables",
        records=arch_delivs,
        record_type="deliverable",
        restore_fn=lambda rid: supabase.table("deliverables").update({"is_archived": False}).eq("id", rid).execute(),
        delete_fn=delete_deliverable_cascade,
        name_fn=lambda r: r.get("name", "?"),
        parent_fn=lambda r: proj_map.get(r.get("project_id"), "—"),
    )

    arch_tasks = get_archived_tasks()
    _archive_section(
        label="Archived Tasks",
        records=arch_tasks,
        record_type="task",
        restore_fn=lambda rid: supabase.table("tasks").update({"is_archived": False}).eq("id", rid).execute(),
        delete_fn=delete_task_cascade,
        name_fn=lambda r: f"{r.get('sequence_id', '')} — {r.get('name', '?')}",
        parent_fn=lambda r: proj_map.get(r.get("project_id"), "—"),
    )

    arch_subs = get_archived_subtasks()

    def _sub_parent(r):
        task_id = r.get("task_id")
        if not task_id:
            return "—"
        try:
            row = supabase.table("tasks").select("name, project_id").eq("id", task_id).execute().data
            if row:
                proj = proj_map.get(row[0].get("project_id"), "—")
                return f"{row[0].get('name', '?')} · {proj}"
        except Exception:
            pass
        return "—"

    _archive_section(
        label="Archived Subtasks",
        records=arch_subs,
        record_type="subtask",
        restore_fn=lambda rid: supabase.table("subtasks").update({"is_archived": False}).eq("id", rid).execute(),
        delete_fn=lambda rid: supabase.table("subtasks").delete().eq("id", rid).execute(),
        name_fn=lambda r: r.get("name", "?"),
        parent_fn=_sub_parent,
    )


# ─── TAB 4: Settings & Notifications ─────────────────────────────────────────

def _tab_settings():
    st.subheader("SMTP Configuration")
    st.info(
        "⚠️ Store this configuration securely. "
        "The password is saved in the database."
    )

    cfg = get_settings()

    with st.form("smtp_form"):
        s1, s2 = st.columns(2)
        with s1:
            smtp_host      = st.text_input("SMTP Host",    value=cfg.get("smtp_host", "smtp.gmail.com"))
            smtp_user      = st.text_input("Sender Email", value=cfg.get("smtp_user", "maiclab@unical.it"))
            smtp_from_name = st.text_input("Sender Name",  value=cfg.get("smtp_from_name", "MAIC LAB"))
        with s2:
            smtp_port     = st.number_input("Port", value=int(cfg.get("smtp_port", 587)),
                                            min_value=1, max_value=65535, step=1)
            smtp_password = st.text_input("Password", value=cfg.get("smtp_password", ""), type="password")
            app_url       = st.text_input("App URL",  value=cfg.get("app_url", "http://localhost:8501"))

        notifications_enabled = st.toggle(
            "Email notifications enabled",
            value=bool(cfg.get("notifications_enabled", False)),
        )

        st.divider()
        st.markdown("**Deadline threshold**")
        threshold = st.number_input(
            "Send deadline reminder X days before due date",
            value=int(cfg.get("expiring_threshold_days", 7)),
            min_value=1, max_value=90, step=1,
        )

        save_btn = st.form_submit_button("💾 Save Configuration", type="primary")

    if save_btn:
        updates = {
            "smtp_host":               smtp_host,
            "smtp_port":               int(smtp_port),
            "smtp_user":               smtp_user,
            "smtp_password":           smtp_password,
            "smtp_from_name":          smtp_from_name,
            "notifications_enabled":   notifications_enabled,
            "app_url":                 app_url,
            "expiring_threshold_days": int(threshold),
        }
        ok, err = save_settings(updates)
        if ok:
            st.success("Configuration saved.")
            if err:
                st.warning(err)
                with st.expander("🔧 Required SQL Migration", expanded=False):
                    st.caption(
                        "Some settings columns are missing in Supabase. "
                        "Run this SQL in Supabase → SQL Editor to enable all fields:"
                    )
                    st.code(SETTINGS_MIGRATION_SQL, language="sql")
        else:
            st.error(f"Save error: {err}")
            with st.expander("🔧 Required SQL Migration", expanded=True):
                st.caption(
                    "SMTP columns do not yet exist in the Supabase database. "
                    "Run this SQL in Supabase → SQL Editor:"
                )
                st.code(SETTINGS_MIGRATION_SQL, language="sql")

    st.divider()
    st.subheader("Google Sheets Backup")
    st.caption("Copy all main tables from Supabase into the configured Google Sheet.")

    if st.button("☁️ Run Backup to Google Sheets", type="primary", use_container_width=True):
        try:
            from utils.sync_to_sheets import backup_supabase_to_sheets
            with st.spinner("Sync in progress..."):
                ok, msg = backup_supabase_to_sheets()
            if ok:
                st.success(msg)
            else:
                st.error(msg)
        except Exception as e:
            st.error(f"Backup error: {e}")

    st.divider()
    st.subheader("Test Email")
    admin_email = st.session_state.get("user_email", "")
    test_target = st.text_input("Test email recipient", value=admin_email)
    if st.button("📧 Send Test Email"):
        from utils.notifications import send_test_email
        ok, msg = send_test_email(test_target)
        if ok:
            st.success(msg)
        else:
            st.error(msg)

    st.divider()
    st.subheader("SQL Schema — Migrations")
    with st.expander("Show required SQL for Supabase", expanded=False):
        st.code(SETTINGS_MIGRATION_SQL, language="sql")
        st.code(DELIVERABLES_MIGRATION_SQL, language="sql")
        st.code(PROJECTS_MIGRATION_SQL, language="sql")


# ─── Main entry point ─────────────────────────────────────────────────────────

def show_admin():
    if st.session_state.get("user_role") != "admin":
        st.error("⛔ Restricted area — administrators only.")
        return

    st.title("⚙️ Admin Panel")

    tab_users, tab_projects, tab_archive, tab_settings = st.tabs([
        "👥 Users",
        "🗂️ Projects",
        "🗄️ Archive",
        "📧 Settings & Notifications",
    ])

    with tab_users:
        _tab_users()

    with tab_projects:
        _tab_projects()

    with tab_archive:
        _tab_archive()

    with tab_settings:
        _tab_settings()
