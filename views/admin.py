"""views/admin.py — Pannello Amministrativo MAIC LAB.

Accessibile solo agli utenti con ruolo 'admin'.
Tabs: Gestione Utenti | Archivio | Impostazioni & Notifiche
"""

import streamlit as st
import datetime
from core.supabase_client import supabase
from db import (
    get_archived_projects, get_archived_deliverables,
    get_archived_tasks, get_archived_subtasks,
    delete_task_cascade, delete_deliverable_cascade, delete_project_cascade,
    get_settings, save_settings, SETTINGS_MIGRATION_SQL,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _fmt_date(d: str | None) -> str:
    if not d:
        return "—"
    try:
        return datetime.date.fromisoformat(d).strftime("%d/%m/%Y")
    except Exception:
        return d or "—"


def _projects_map() -> dict:
    rows = supabase.table("projects").select("id, name").execute().data
    return {r["id"]: r["name"] for r in rows}


def _deliverables_map() -> dict:
    rows = supabase.table("deliverables").select("id, name, project_id").execute().data
    return {r["id"]: r for r in rows}


# ─── TAB 1: Gestione Utenti ───────────────────────────────────────────────────

def _tab_users():
    st.subheader("Utenti del sistema")

    try:
        users = supabase.table("users").select("*").order("name").execute().data
    except Exception as e:
        st.error(f"Errore caricamento utenti: {e}")
        return

    if not users:
        st.info("Nessun utente presente.")
    else:
        # Header row
        hc1, hc2, hc3, hc4, hc5, hc6 = st.columns([2.5, 3, 1.5, 1.5, 1.5, 1.5])
        hc1.markdown("**Nome**")
        hc2.markdown("**Email**")
        hc3.markdown("**Ruolo**")
        hc4.markdown("**Stato**")
        hc5.markdown("**Modifica**")
        hc6.markdown("**Disattiva**")
        st.divider()

        for u in users:
            email     = u["email"]
            name      = u.get("name", email)
            role      = u.get("role", "user")
            approved  = u.get("is_approved", False)
            stato     = "Attivo" if approved else "Disattivato"
            stato_col = "🟢" if approved else "🔴"

            c1, c2, c3, c4, c5, c6 = st.columns([2.5, 3, 1.5, 1.5, 1.5, 1.5])
            c1.write(name)
            c2.write(email)
            c3.write(role.capitalize())
            c4.write(f"{stato_col} {stato}")

            with c5:
                new_role = "user" if role == "admin" else "admin"
                btn_label = f"→ {new_role}"
                if st.button(btn_label, key=f"role_{email}", use_container_width=True):
                    supabase.table("users").update({"role": new_role}).eq("email", email).execute()
                    st.success(f"Ruolo cambiato a {new_role}.")
                    st.rerun()

            with c6:
                if approved:
                    if st.button("Disattiva", key=f"deact_{email}", use_container_width=True):
                        supabase.table("users").update({"is_approved": False}).eq("email", email).execute()
                        st.warning(f"{name} disattivato.")
                        st.rerun()
                else:
                    if st.button("Riattiva", key=f"react_{email}", use_container_width=True):
                        supabase.table("users").update({"is_approved": True}).eq("email", email).execute()
                        st.success(f"{name} riattivato.")
                        st.rerun()

    st.divider()

    # ── Aggiungi nuovo utente ──────────────────────────────────────────────
    st.subheader("Aggiungi nuovo utente")
    with st.form("add_user_form", clear_on_submit=True):
        f1, f2, f3 = st.columns([2, 2.5, 1.5])
        with f1:
            new_name = st.text_input("Nome completo*")
        with f2:
            new_email = st.text_input("Email*")
        with f3:
            new_role = st.selectbox("Ruolo", ["user", "admin"])

        submitted = st.form_submit_button("Aggiungi utente", type="primary")
        if submitted:
            if not new_name or not new_email:
                st.error("Nome e email sono obbligatori.")
            else:
                # Check duplicate
                existing = supabase.table("users").select("email").eq("email", new_email).execute().data
                if existing:
                    st.error(f"L'email {new_email} è già registrata nel sistema.")
                else:
                    try:
                        supabase.table("users").insert({
                            "email":       new_email,
                            "name":        new_name,
                            "role":        new_role,
                            "is_approved": True,
                            "avatar_color": "#{:06x}".format(abs(hash(new_email)) % 0xFFFFFF),
                        }).execute()
                        st.success(f"Utente {new_name} aggiunto con successo.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Errore: {e}")


# ─── TAB 2: Archivio e cancellazione ─────────────────────────────────────────

def _confirm_key(record_type: str, record_id) -> str:
    return f"confirm_delete_{record_type}_{record_id}"


def _archive_section(label: str, records: list, record_type: str,
                     restore_fn, delete_fn, name_fn, parent_fn):
    count = len(records)
    with st.expander(f"{label} ({count})", expanded=False):
        if not records:
            st.caption("Nessun record archiviato.")
            return
        for r in records:
            rid       = r["id"]
            rname     = name_fn(r)
            parent    = parent_fn(r)
            updated   = _fmt_date(r.get("updated_at") or r.get("deadline"))
            ck        = _confirm_key(record_type, rid)

            with st.container(border=True):
                col_info, col_restore, col_delete = st.columns([5, 1.5, 1.5])
                with col_info:
                    st.write(f"**{rname}**")
                    if parent:
                        st.caption(f"Progetto: {parent}  ·  ultima modifica: {updated}")
                    else:
                        st.caption(f"ultima modifica: {updated}")

                with col_restore:
                    if st.button("↩ Ripristina", key=f"restore_{record_type}_{rid}", use_container_width=True):
                        restore_fn(rid)
                        st.success(f"'{rname}' ripristinato.")
                        st.rerun()

                with col_delete:
                    if st.button("🗑 Elimina", key=f"del_{record_type}_{rid}",
                                 use_container_width=True, type="secondary"):
                        st.session_state[ck] = True

                # Inline confirmation
                if st.session_state.get(ck):
                    st.warning(
                        f"⚠️ Questa operazione è irreversibile. "
                        f"Confermi la cancellazione di **{rname}**?"
                    )
                    yes_col, no_col = st.columns(2)
                    with yes_col:
                        if st.button("Sì, elimina", key=f"yes_{record_type}_{rid}",
                                     type="primary", use_container_width=True):
                            try:
                                delete_fn(rid)
                                st.success(f"'{rname}' eliminato definitivamente.")
                                del st.session_state[ck]
                                st.rerun()
                            except Exception as e:
                                st.error(f"Errore: {e}")
                    with no_col:
                        if st.button("Annulla", key=f"no_{record_type}_{rid}",
                                     use_container_width=True):
                            del st.session_state[ck]
                            st.rerun()


def _tab_archive():
    st.subheader("Archivio")
    st.caption("Tutti i record archiviati. Ripristina o elimina definitivamente.")

    proj_map  = _projects_map()
    deliv_map = _deliverables_map()

    # ── Progetti archiviati ───────────────────────────────────────────────
    arch_projs = get_archived_projects()
    _archive_section(
        label="Progetti archiviati",
        records=arch_projs,
        record_type="project",
        restore_fn=lambda rid: supabase.table("projects").update({"is_archived": False}).eq("id", rid).execute(),
        delete_fn=delete_project_cascade,
        name_fn=lambda r: f"{r.get('name', '?')} ({r.get('acronym', '')})",
        parent_fn=lambda r: "",
    )

    # ── Deliverable archiviati ────────────────────────────────────────────
    arch_delivs = get_archived_deliverables()
    _archive_section(
        label="Deliverable archiviati",
        records=arch_delivs,
        record_type="deliverable",
        restore_fn=lambda rid: supabase.table("deliverables").update({"is_archived": False}).eq("id", rid).execute(),
        delete_fn=delete_deliverable_cascade,
        name_fn=lambda r: r.get("name", "?"),
        parent_fn=lambda r: proj_map.get(r.get("project_id"), "—"),
    )

    # ── Task archiviati ───────────────────────────────────────────────────
    arch_tasks = get_archived_tasks()
    _archive_section(
        label="Task archiviati",
        records=arch_tasks,
        record_type="task",
        restore_fn=lambda rid: supabase.table("tasks").update({"is_archived": False}).eq("id", rid).execute(),
        delete_fn=delete_task_cascade,
        name_fn=lambda r: f"{r.get('sequence_id', '')} — {r.get('name', '?')}",
        parent_fn=lambda r: proj_map.get(r.get("project_id"), "—"),
    )

    # ── Subtask archiviati ────────────────────────────────────────────────
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
        label="Subtask archiviati",
        records=arch_subs,
        record_type="subtask",
        restore_fn=lambda rid: supabase.table("subtasks").update({"is_archived": False}).eq("id", rid).execute(),
        delete_fn=lambda rid: supabase.table("subtasks").delete().eq("id", rid).execute(),
        name_fn=lambda r: r.get("name", "?"),
        parent_fn=_sub_parent,
    )


# ─── TAB 3: Impostazioni & Notifiche ─────────────────────────────────────────

def _tab_settings():
    st.subheader("Configurazione SMTP")
    st.info(
        "⚠️ Conserva questa configurazione in modo sicuro. "
        "La password viene salvata nel database."
    )

    cfg = get_settings()

    with st.form("smtp_form"):
        s1, s2 = st.columns(2)
        with s1:
            smtp_host = st.text_input("Host SMTP", value=cfg.get("smtp_host", "smtp.gmail.com"))
            smtp_user = st.text_input("Email mittente", value=cfg.get("smtp_user", "maiclab@unical.it"))
            smtp_from_name = st.text_input("Nome mittente", value=cfg.get("smtp_from_name", "MAIC LAB"))
        with s2:
            smtp_port = st.number_input("Porta", value=int(cfg.get("smtp_port", 587)), min_value=1, max_value=65535, step=1)
            smtp_password = st.text_input("Password", value=cfg.get("smtp_password", ""), type="password")
            app_url = st.text_input("URL App", value=cfg.get("app_url", "http://localhost:8501"))

        notifications_enabled = st.toggle(
            "Notifiche email attive",
            value=bool(cfg.get("notifications_enabled", False))
        )

        st.divider()
        st.markdown("**Soglia scadenze**")
        threshold = st.number_input(
            "Invia notifica di scadenza X giorni prima",
            value=int(cfg.get("expiring_threshold_days", 7)),
            min_value=1, max_value=90, step=1
        )

        save_btn = st.form_submit_button("💾 Salva configurazione", type="primary")

    if save_btn:
        updates = {
            "smtp_host":             smtp_host,
            "smtp_port":             int(smtp_port),
            "smtp_user":             smtp_user,
            "smtp_password":         smtp_password,
            "smtp_from_name":        smtp_from_name,
            "notifications_enabled": notifications_enabled,
            "app_url":               app_url,
            "expiring_threshold_days": int(threshold),
        }
        ok, err = save_settings(updates)
        if ok:
            st.success("Configurazione salvata.")
        else:
            st.error(f"Errore nel salvataggio: {err}")
            with st.expander("🔧 Migrazione SQL richiesta", expanded=True):
                st.caption(
                    "Le colonne SMTP non esistono ancora nel database Supabase. "
                    "Esegui questo SQL nel pannello Supabase → SQL Editor:"
                )
                st.code(SETTINGS_MIGRATION_SQL, language="sql")

    st.divider()
    st.subheader("Test email")
    admin_email = st.session_state.get("user_email", "")
    test_target = st.text_input("Destinatario email di test", value=admin_email)
    if st.button("📧 Invia email di test"):
        from utils.notifications import send_test_email
        ok, msg = send_test_email(test_target)
        if ok:
            st.success(msg)
        else:
            st.error(msg)

    st.divider()
    st.subheader("Schema SQL — migrazioni")
    with st.expander("Mostra SQL necessario per Supabase", expanded=False):
        st.code(SETTINGS_MIGRATION_SQL, language="sql")


# ─── Main entry point ─────────────────────────────────────────────────────────

def show_admin():
    if st.session_state.get("user_role") != "admin":
        st.error("⛔ Area riservata agli amministratori.")
        return

    st.title("⚙️ Pannello Amministrativo")

    tab_users, tab_archive, tab_settings = st.tabs([
        "👥 Gestione Utenti",
        "🗄️ Archivio",
        "📧 Impostazioni & Notifiche",
    ])

    with tab_users:
        _tab_users()

    with tab_archive:
        _tab_archive()

    with tab_settings:
        _tab_settings()
