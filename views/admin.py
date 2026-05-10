"""views/admin.py — MAIC LAB Admin Panel.

Accessible only to users with role 'admin'.
Tabs: Users | Projects | Archive | Settings & Notifications
"""

import streamlit as st
import datetime
import json
import pandas as pd
from core.supabase_client import supabase
from db import (
    get_archived_projects, get_archived_deliverables,
    get_archived_tasks, get_archived_subtasks,
    delete_task_cascade, delete_deliverable_cascade, delete_project_cascade,
    get_settings, save_settings, SETTINGS_MIGRATION_SQL, DELIVERABLES_MIGRATION_SQL,
    PROJECTS_MIGRATION_SQL, SCOPUS_MIGRATION_SQL,
)
from utils.md_editor import markdown_editor
from utils.helpers import DELIVERABLE_TAG_PALETTE, parse_deliverable_tag_styles


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


def _reset_md_editor_state(editor_key: str) -> None:
    """Clear markdown editor state to force a fresh value load on next render."""
    st.session_state.pop(f"__mde_{editor_key}", None)
    st.session_state.pop(f"{editor_key}_ta", None)


def _reset_project_edit_state(pid: int) -> None:
    """Clear project edit widget state so reopened forms always start from DB values."""
    for k in [
        f"p_name_{pid}",
        f"p_acro_{pid}",
        f"p_idf_{pid}",
        f"p_fund_{pid}",
        f"p_start_{pid}",
        f"p_end_{pid}",
        f"p_desc_{pid}",
    ]:
        st.session_state.pop(k, None)


def _normalize_email(raw: str) -> str:
    return (raw or "").strip().lower()


def _reassign_user_references(old_email: str, new_email: str) -> None:
    """Move all FK references from old_email to new_email."""
    supabase.table("deliverables").update({"owner_email": new_email}).eq("owner_email", old_email).execute()
    supabase.table("deliverables").update({"supervisor_email": new_email}).eq("supervisor_email", old_email).execute()
    supabase.table("tasks").update({"owner_email": new_email}).eq("owner_email", old_email).execute()
    supabase.table("tasks").update({"supervisor_email": new_email}).eq("supervisor_email", old_email).execute()
    supabase.table("subtasks").update({"owner_email": new_email}).eq("owner_email", old_email).execute()
    supabase.table("subtasks").update({"supervisor_email": new_email}).eq("supervisor_email", old_email).execute()
    supabase.table("comments").update({"author_email": new_email}).eq("author_email", old_email).execute()


def _clear_user_references(email: str) -> None:
    """Nullify all FK references to a user before deletion when DB FK is strict."""
    supabase.table("deliverables").update({"owner_email": None}).eq("owner_email", email).execute()
    supabase.table("deliverables").update({"supervisor_email": None}).eq("supervisor_email", email).execute()
    supabase.table("tasks").update({"owner_email": None}).eq("owner_email", email).execute()
    supabase.table("tasks").update({"supervisor_email": None}).eq("supervisor_email", email).execute()
    supabase.table("subtasks").update({"owner_email": None}).eq("owner_email", email).execute()
    supabase.table("subtasks").update({"supervisor_email": None}).eq("supervisor_email", email).execute()
    supabase.table("comments").update({"author_email": None}).eq("author_email", email).execute()


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

                    st.markdown("**Publications & PhD tracking**")
                    sf1, sf2 = st.columns(2)
                    with sf1:
                        e_scopus_id = st.text_input(
                            "Scopus Author ID",
                            value=u.get("scopus_id") or "",
                            key=f"e_scopus_{safe_key}",
                            help="Numeric ID from scopus.com → Author profile URL.",
                        )
                    with sf2:
                        e_is_phd = st.checkbox(
                            "PhD student",
                            value=bool(u.get("is_phd_student")),
                            key=f"e_phd_{safe_key}",
                        )

                    if e_is_phd:
                        pf1, pf2 = st.columns(2)
                        with pf1:
                            e_phd_start = st.date_input(
                                "PhD Start Date",
                                value=_parse_date(u.get("phd_start_date")),
                                format="DD/MM/YYYY",
                                key=f"e_phd_start_{safe_key}",
                            )
                        with pf2:
                            e_phd_end = st.date_input(
                                "PhD End Date",
                                value=_parse_date(u.get("phd_end_date")),
                                format="DD/MM/YYYY",
                                key=f"e_phd_end_{safe_key}",
                            )
                    else:
                        e_phd_start = None
                        e_phd_end = None

                    sb1, sb2 = st.columns(2)
                    with sb1:
                        if st.button("💾 Save", key=f"save_user_{safe_key}",
                                     type="primary", use_container_width=True):
                            if not e_name or not e_email:
                                st.error("Name and email are required.")
                            else:
                                try:
                                    target_email = _normalize_email(e_email)
                                    current_email = _normalize_email(email)

                                    extra_fields = {
                                        "scopus_id": (e_scopus_id or "").strip() or None,
                                        "is_phd_student": bool(e_is_phd),
                                        "phd_start_date": e_phd_start.isoformat() if e_phd_start else None,
                                        "phd_end_date": e_phd_end.isoformat() if e_phd_end else None,
                                    }

                                    if target_email != current_email:
                                        exists = (
                                            supabase.table("users")
                                            .select("email")
                                            .eq("email", target_email)
                                            .limit(1)
                                            .execute()
                                            .data
                                        )
                                        if exists:
                                            st.error(f"Email {target_email} is already registered.")
                                        else:
                                            supabase.table("users").insert({
                                                "email": target_email,
                                                "name": e_name,
                                                "role": e_role,
                                                "is_approved": approved,
                                                "avatar_color": e_color,
                                                **extra_fields,
                                            }).execute()

                                            _reassign_user_references(current_email, target_email)
                                            supabase.table("users").delete().eq("email", current_email).execute()
                                    else:
                                        supabase.table("users").update({
                                            "name": e_name,
                                            "role": e_role,
                                            "avatar_color": e_color,
                                            **extra_fields,
                                        }).eq("email", current_email).execute()

                                    if target_email == current_email or not exists:
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
                            _clear_user_references(email)
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
                        currently_open = st.session_state.get(edit_key, False)
                        if currently_open:
                            st.session_state.pop(edit_key, None)
                            _reset_project_edit_state(pid)
                        else:
                            _reset_project_edit_state(pid)
                            st.session_state[f"p_name_{pid}"] = pname
                            st.session_state[f"p_acro_{pid}"] = acronym
                            st.session_state[f"p_idf_{pid}"] = identifier
                            st.session_state[f"p_fund_{pid}"] = funding
                            st.session_state[f"p_start_{pid}"] = _parse_date(proj.get("start_date"))
                            st.session_state[f"p_end_{pid}"] = _parse_date(proj.get("end_date"))
                            st.session_state[f"p_desc_{pid}"] = proj.get("description") or ""
                            st.session_state[edit_key] = True
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
                    with st.form(f"edit_proj_form_{pid}"):
                        pf1, pf2 = st.columns(2)
                        with pf1:
                            p_name    = st.text_input("Project Name*", key=f"p_name_{pid}")
                            p_acronym = st.text_input("Acronym",       key=f"p_acro_{pid}")
                            p_idf     = st.text_input("Identifier",    key=f"p_idf_{pid}")
                        with pf2:
                            p_funding = st.text_input("Funding Agency", key=f"p_fund_{pid}")
                            p_start   = st.date_input(
                                "Start Date",
                                format="DD/MM/YYYY",
                                key=f"p_start_{pid}",
                            )
                            p_end = st.date_input(
                                "End Date",
                                format="DD/MM/YYYY",
                                key=f"p_end_{pid}",
                            )
                        p_description = markdown_editor(
                            value=st.session_state.get(f"p_desc_{pid}", ""),
                            key=f"p_desc_{pid}",
                            height=220,
                            label="📝 Project Description (optional, Markdown)",
                        )
                        pb1, pb2 = st.columns(2)
                        with pb1:
                            save_clicked = st.form_submit_button(
                                "💾 Save", type="primary", use_container_width=True
                            )
                        with pb2:
                            cancel_clicked = st.form_submit_button(
                                "Cancel", use_container_width=True
                            )
                    if cancel_clicked:
                        _reset_project_edit_state(pid)
                        st.session_state.pop(edit_key, None)
                        st.rerun()
                    if save_clicked:
                        if not p_name:
                            st.error("Project name is required.")
                        else:
                            try:
                                new_description = p_description.strip() or None
                                supabase.table("projects").update({
                                    "name":           p_name,
                                    "acronym":        p_acronym or None,
                                    "identifier":     p_idf     or None,
                                    "funding_agency": p_funding or None,
                                    "start_date":     p_start.isoformat() if p_start else None,
                                    "end_date":       p_end.isoformat()   if p_end   else None,
                                    "description":    new_description,
                                }).eq("id", pid).execute()

                                # Verify persistence to surface silent failures.
                                readback = (
                                    supabase.table("projects")
                                    .select("description")
                                    .eq("id", pid)
                                    .limit(1)
                                    .execute()
                                    .data
                                )
                                db_description = None
                                if readback:
                                    db_description = (readback[0].get("description") or "").strip() or None
                                if db_description != new_description:
                                    st.error(
                                        "Save did not persist the new description. "
                                        "Please reopen Edit and save again."
                                    )
                                else:
                                    _reset_project_edit_state(pid)
                                    st.session_state.pop(edit_key, None)
                                    st.success("Project updated.")
                                    st.rerun()
                            except Exception as ex:
                                st.error(f"Error: {ex}")

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
                    _reset_md_editor_state("admin_new_proj_notes")
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
            "Archive **all tasks with status 'Completed'** and related completed subtasks "
            "(they will move to the Archived sections). "
            "This does not delete data; it only sets is_archived = true."
        )
        ac1, ac2 = st.columns(2)
        with ac1:
            if st.button("Yes, archive completed tasks", key="yes_bulk_arch_completed_tasks", type="primary", use_container_width=True):
                try:
                    completed_tasks = (
                        supabase.table("tasks")
                        .select("id")
                        .eq("status", "Completed")
                        .eq("is_archived", False)
                        .execute()
                        .data
                        or []
                    )
                    completed_task_ids = [t["id"] for t in completed_tasks if t.get("id") is not None]

                    if completed_task_ids:
                        supabase.table("tasks").update({"is_archived": True}).in_("id", completed_task_ids).execute()
                        supabase.table("subtasks").update({"is_archived": True}).in_("task_id", completed_task_ids).eq("is_archived", False).execute()

                    # Also archive standalone completed subtasks that may belong to still-active tasks.
                    supabase.table("subtasks").update({"is_archived": True}).eq("status", "Completed").eq("is_archived", False).execute()

                    st.success("Completed tasks and subtasks have been archived.")
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
    st.subheader("Deliverable Tags")
    st.caption("Manage deliverable tag names and colors used across Dashboard, Active Tasks, Deliverables, Reports and Calendar.")
    _tab_deliverable_tags()

    st.divider()

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
        st.markdown("**Weekly briefing**")
        threshold = st.number_input(
            "Weekly briefing: show tasks due within X days",
            value=int(cfg.get("expiring_threshold_days", 14)),
            min_value=1, max_value=30, step=1,
            key="threshold_input",
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
    st.subheader("SQL Migrations")
    st.caption("Run these SQL snippets in Supabase to keep the schema aligned with the app.")
    with st.expander("Settings & notification schema", expanded=False):
        st.code(SETTINGS_MIGRATION_SQL, language="sql")
    with st.expander("Scopus & PhD tracking (users table)", expanded=False):
        st.caption("Adds scopus_id, is_phd_student, phd_start_date, phd_end_date to users.")
        st.code(SCOPUS_MIGRATION_SQL, language="sql")

def _tab_deliverable_tags():
    cfg = get_settings()

    st.subheader("Deliverable Tags")
    st.caption(
        "Manage deliverable tag names and assign one color from the fixed palette. "
        "These tags are used in Active Tasks, Reports and Calendar."
    )

    palette_labels = {
        f"Type 1 - Dark Teal ({DELIVERABLE_TAG_PALETTE['Dark Teal']})": DELIVERABLE_TAG_PALETTE["Dark Teal"],
        f"Type 2 - Navy Blue ({DELIVERABLE_TAG_PALETTE['Navy Blue']})": DELIVERABLE_TAG_PALETTE["Navy Blue"],
        f"Type 3 - Deep Eggplant ({DELIVERABLE_TAG_PALETTE['Deep Eggplant']})": DELIVERABLE_TAG_PALETTE["Deep Eggplant"],
        f"Type 4 - Charcoal Gray ({DELIVERABLE_TAG_PALETTE['Charcoal Gray']})": DELIVERABLE_TAG_PALETTE["Charcoal Gray"],
        f"Type 5 - Dark Burgundy ({DELIVERABLE_TAG_PALETTE['Dark Burgundy']})": DELIVERABLE_TAG_PALETTE["Dark Burgundy"],
    }
    color_to_label = {v.upper(): k for k, v in palette_labels.items()}

    raw_styles = parse_deliverable_tag_styles(cfg.get("deliverable_tag_styles"))
    table_rows = []
    for style in raw_styles:
        color = (style.get("color") or "#334155").upper()
        table_rows.append(
            {
                "Tag": style.get("name", ""),
                "Palette": color_to_label.get(color, list(palette_labels.keys())[0]),
            }
        )

    edited_df = st.data_editor(
        pd.DataFrame(table_rows, columns=["Tag", "Palette"]),
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        key="admin_deliverable_tag_editor",
        column_config={
            "Tag": st.column_config.TextColumn(
                "Tag",
                required=False,
                help="Leave empty to disable this row.",
            ),
            "Palette": st.column_config.SelectboxColumn(
                "Palette",
                required=True,
                options=list(palette_labels.keys()),
            ),
        },
    )

    if st.button("💾 Save Deliverable Tags", type="primary", use_container_width=True):
        new_styles = []
        seen = set()
        for row in edited_df.to_dict("records"):
            tag_name = str(row.get("Tag", "")).strip()
            if not tag_name:
                continue
            key = tag_name.lower()
            if key in seen:
                st.error(f"Duplicate tag: {tag_name}")
                return
            seen.add(key)
            color_label = row.get("Palette")
            color_value = palette_labels.get(color_label, DELIVERABLE_TAG_PALETTE["Charcoal Gray"])
            new_styles.append({"name": tag_name, "color": color_value})

        if not new_styles:
            st.error("Add at least one deliverable tag.")
            return

        updates = {
            "deliverable_types": json.dumps([s["name"] for s in new_styles]),
            "deliverable_tag_styles": json.dumps(new_styles),
        }
        ok, err = save_settings(updates)
        if ok:
            st.success("Deliverable tag settings saved.")
            if err:
                st.warning(err)
        else:
            st.error(f"Save error: {err}")
            with st.expander("🔧 Required SQL Migration", expanded=True):
                st.caption(
                    "Settings columns are missing in Supabase. "
                    "Run this SQL in Supabase → SQL Editor:"
                )
                st.code(SETTINGS_MIGRATION_SQL, language="sql")

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
