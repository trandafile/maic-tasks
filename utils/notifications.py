"""utils/notifications.py — Email notification helpers.

All functions:
- Read SMTP config from DB settings before every send.
- If notifications_enabled=False or smtp_password is empty: log to console only.
- Handle SMTP exceptions gracefully without raising.
"""

import smtplib
import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


def _get_settings() -> dict:
    try:
        from db import get_settings
        return get_settings()
    except Exception:
        return {}


def _send(subject: str, body: str, to_email: str) -> bool:
    """Low-level send via STARTTLS. Returns True on success."""
    cfg = _get_settings()

    if not cfg.get("notifications_enabled"):
        print(f"[notifications] Notifiche disabilitate — salto invio a {to_email}: {subject}")
        return False

    password = cfg.get("smtp_password", "")
    if not password:
        print(f"[notifications] smtp_password non configurata — salto invio a {to_email}: {subject}")
        return False

    host      = cfg.get("smtp_host", "smtp.gmail.com")
    port      = int(cfg.get("smtp_port", 587))
    user      = cfg.get("smtp_user", "")
    from_name = cfg.get("smtp_from_name", "MAIC LAB")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"{from_name} <{user}>"
    msg["To"]      = to_email
    msg.attach(MIMEText(body, "plain", "utf-8"))

    try:
        with smtplib.SMTP(host, port, timeout=10) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(user, password)
            server.sendmail(user, [to_email], msg.as_string())
        print(f"[notifications] Email inviata a {to_email}: {subject}")
        return True
    except Exception as e:
        print(f"[notifications] Errore invio a {to_email}: {e}")
        return False


def _fmt_date(d: str | None) -> str:
    if not d:
        return "—"
    try:
        return datetime.date.fromisoformat(d).strftime("%d/%m/%Y")
    except Exception:
        return d


def _get_name_from_email(email: str) -> str:
    """Try to resolve display name from users table."""
    try:
        from core.supabase_client import supabase
        rows = supabase.table("users").select("name").eq("email", email).execute().data
        if rows:
            return rows[0].get("name", email)
    except Exception:
        pass
    return email


def send_task_assigned(task: dict, assignee_email: str, assigner_name: str) -> bool:
    """Notify assignee that a task has been assigned to them."""
    if not assignee_email:
        return False

    cfg       = _get_settings()
    app_url   = cfg.get("app_url", "http://localhost:8501")
    recipient_name = _get_name_from_email(assignee_email).split()[0]

    seq_id    = task.get("sequence_id") or f"T-{task.get('id', '?')}"
    task_name = task.get("name", "")
    deadline  = _fmt_date(task.get("deadline"))
    priority  = (task.get("priority") or "none").capitalize()
    project   = task.get("project_name", "")
    deliv     = task.get("deliverable_name", "")

    deliv_line = f"Deliverable: {deliv}\n" if deliv else ""

    subject = f"[MAIC LAB] Nuovo task assegnato: {seq_id} — {task_name}"
    body = (
        f"Ciao {recipient_name},\n\n"
        f"Ti è stato assegnato un nuovo task nel progetto {project}.\n\n"
        f"Task: {seq_id} — {task_name}\n"
        f"{deliv_line}"
        f"Scadenza: {deadline}\n"
        f"Priorità: {priority}\n"
        f"Assegnato da: {assigner_name}\n\n"
        f"Accedi all'app per i dettagli: {app_url}\n\n"
        f"— MAIC LAB Task Manager"
    )
    return _send(subject, body, assignee_email)


def send_deadline_reminder(task: dict, assignee_email: str, days_left: int) -> bool:
    """Notify assignee that deadline is approaching."""
    if not assignee_email:
        return False

    cfg       = _get_settings()
    app_url   = cfg.get("app_url", "http://localhost:8501")
    recipient_name = _get_name_from_email(assignee_email).split()[0]

    seq_id    = task.get("sequence_id") or f"T-{task.get('id', '?')}"
    task_name = task.get("name", "")
    deadline  = _fmt_date(task.get("deadline"))
    priority  = (task.get("priority") or "none").capitalize()
    project   = task.get("project_name", "")

    subject = f"[MAIC LAB] Scadenza imminente: {seq_id} — {task_name} ({days_left}gg)"
    body = (
        f"Ciao {recipient_name},\n\n"
        f"Il task seguente scade tra {days_left} giorno/i.\n\n"
        f"Task: {seq_id} — {task_name}\n"
        f"Progetto: {project}\n"
        f"⚠️  Scadenza: {deadline} (tra {days_left} gg)\n"
        f"Priorità: {priority}\n\n"
        f"Accedi all'app per aggiornare lo stato: {app_url}\n\n"
        f"— MAIC LAB Task Manager"
    )
    return _send(subject, body, assignee_email)


def send_task_overdue(task: dict, assignee_email: str) -> bool:
    """Notify assignee that task deadline has passed."""
    if not assignee_email:
        return False

    cfg       = _get_settings()
    app_url   = cfg.get("app_url", "http://localhost:8501")
    recipient_name = _get_name_from_email(assignee_email).split()[0]

    seq_id    = task.get("sequence_id") or f"T-{task.get('id', '?')}"
    task_name = task.get("name", "")
    deadline  = _fmt_date(task.get("deadline"))
    project   = task.get("project_name", "")

    subject = f"[MAIC LAB] Task scaduto: {seq_id} — {task_name}"
    body = (
        f"Ciao {recipient_name},\n\n"
        f"Il task seguente ha superato la scadenza senza essere completato.\n\n"
        f"Task: {seq_id} — {task_name}\n"
        f"Progetto: {project}\n"
        f"❌ Scadenza: {deadline} (scaduto)\n\n"
        f"Accedi all'app per aggiornare lo stato: {app_url}\n\n"
        f"— MAIC LAB Task Manager"
    )
    return _send(subject, body, assignee_email)


def send_test_email(to_email: str) -> tuple[bool, str]:
    """Send a test email. Returns (success, message)."""
    subject = "[MAIC LAB] Test configurazione email"
    body = (
        "Questa è un'email di test inviata dal pannello Admin di MAIC LAB Task Manager.\n\n"
        "Se hai ricevuto questo messaggio, la configurazione SMTP è corretta.\n\n"
        "— MAIC LAB Task Manager"
    )
    ok = _send(subject, body, to_email)
    if ok:
        return True, "Email di test inviata con successo."
    else:
        cfg = _get_settings()
        if not cfg.get("notifications_enabled"):
            return False, "Le notifiche sono disabilitate. Attivale prima di inviare il test."
        if not cfg.get("smtp_password"):
            return False, "Password SMTP non configurata."
        return False, "Invio fallito. Controlla la console per i dettagli."


def send_master_status_report_to_admins(subject: str, body: str) -> tuple[bool, int, int]:
    """Send the Master Status Report to all approved admins.

    Returns:
        (all_sent_ok, sent_count, total_admins)
    """
    try:
        from core.supabase_client import supabase
        admins = (
            supabase.table("users")
            .select("email")
            .eq("role", "admin")
            .eq("is_approved", True)
            .execute()
            .data
            or []
        )
        emails = [a.get("email") for a in admins if a.get("email")]
    except Exception as e:
        print(f"[notifications] Error fetching admins: {e}")
        return False, 0, 0

    sent = 0
    ok_all = True
    for em in emails:
        ok = _send(subject=subject, body=body, to_email=em)
        sent += 1 if ok else 0
        ok_all = ok_all and ok
    return ok_all, sent, len(emails)


_MONTHS_IT = {
    1: "gennaio",
    2: "febbraio",
    3: "marzo",
    4: "aprile",
    5: "maggio",
    6: "giugno",
    7: "luglio",
    8: "agosto",
    9: "settembre",
    10: "ottobre",
    11: "novembre",
    12: "dicembre",
}


def _fmt_date_slash(d: str | None) -> str:
    if not d:
        return "—"
    try:
        return datetime.date.fromisoformat(d).strftime("%Y/%m/%d")
    except Exception:
        return d


def _fmt_date_it_long(value: datetime.date) -> str:
    return f"{value.day:02d} {_MONTHS_IT[value.month]} {value.year}"


def _delta_label(dl_str: str | None) -> str:
    if not dl_str:
        return "senza scadenza"
    try:
        delta = (datetime.date.fromisoformat(dl_str) - datetime.date.today()).days
    except Exception:
        return "scadenza non valida"
    if delta < 0:
        return f"scaduto da {abs(delta)} giorni"
    if delta == 0:
        return "scade oggi"
    return f"tra {delta} giorni"


def _task_sort_key(item: dict) -> tuple[int, str, str]:
    deadline = item.get("deadline") or "9999-12-31"
    return (0 if item.get("deadline") else 1, deadline, str(item.get("sequence_id") or ""))


def _sequence_label(item: dict) -> str:
    if item.get("sequence_id"):
        return str(item["sequence_id"])
    return f"T-{item.get('id', '?')}"


def send_weekly_briefing(
    to_email: str,
    name: str,
    overdue: list[dict],
    upcoming: list[dict],
    active: list[dict],
    supervised_blocked: list[dict],
    threshold: int = 14,
) -> bool:
    """Build and send the weekly plain-text digest."""
    if not to_email:
        return False

    cfg = _get_settings()
    app_url = cfg.get("app_url", "http://localhost:8501")
    today = datetime.date.today()
    monday = today - datetime.timedelta(days=today.weekday())
    friday = monday + datetime.timedelta(days=4)
    first_name = (name or to_email).split()[0]

    overdue_sorted = sorted(overdue, key=_task_sort_key)
    upcoming_sorted = sorted(upcoming, key=_task_sort_key)
    active_sorted = sorted(active, key=_task_sort_key)
    supervised_sorted = sorted(supervised_blocked, key=_task_sort_key)

    combined = []
    seen = set()
    for item in overdue_sorted + upcoming_sorted + active_sorted:
        key = (item.get("id"), item.get("task_id"), item.get("sequence_id"), item.get("name"))
        if key in seen:
            continue
        seen.add(key)
        combined.append(item)
    combined.sort(key=_task_sort_key)

    if overdue_sorted or upcoming_sorted:
        intro = f"Hai {len(overdue_sorted)} task scaduti e {len(upcoming_sorted)} in scadenza da gestire."
    else:
        intro = (
            "Non hai scadenze imminenti questa settimana. "
            "Di seguito trovi tutti i tuoi task attivi."
        )

    lines = [
        f"Ciao {first_name},",
        "",
        f"Ecco il tuo riepilogo per la settimana del {_fmt_date_it_long(monday)} - {_fmt_date_it_long(friday)}.",
        intro,
        "",
    ]

    if overdue_sorted:
        lines.append(f"-- SCADUTI ({len(overdue_sorted)}) --")
        for item in overdue_sorted:
            lines.append(f"• {_sequence_label(item)} — {item.get('name', '')}")
            lines.append(
                f"  {_delta_label(item.get('deadline'))} · Status: {item.get('status') or '—'} · Progetto: {item.get('project_acronym') or '—'}"
            )
        lines.append("")

    if upcoming_sorted:
        lines.append(f"-- IN SCADENZA ENTRO {threshold} GIORNI ({len(upcoming_sorted)}) --")
        for item in upcoming_sorted:
            lines.append(f"• {_sequence_label(item)} — {item.get('name', '')}")
            lines.append(
                f"  Scadenza: {_fmt_date_slash(item.get('deadline'))} · {_delta_label(item.get('deadline'))} · Status: {item.get('status') or '—'}"
            )
            lines.append(f"  Progetto: {item.get('project_acronym') or '—'}")
        lines.append("")

    if supervised_sorted:
        lines.append(f"-- DA SBLOCCARE - IN SUPERVISIONE ({len(supervised_sorted)}) --")
        for item in supervised_sorted:
            owner_label = item.get("owner_name") or item.get("owner_email") or "—"
            lines.append(f"• {_sequence_label(item)} — {item.get('name', '')}")
            lines.append(
                f"  Progetto: {item.get('project_acronym') or '—'} · Assegnato a: {owner_label}"
            )
        lines.append("")

    lines.append(f"-- TUTTI I TUOI TASK ATTIVI ({len(combined)}) --")
    for item in combined:
        lines.append(f"• {_sequence_label(item)} — {item.get('name', '')}")
        lines.append(
            f"  [{item.get('status') or '—'}] scadenza {_fmt_date_slash(item.get('deadline'))} · {item.get('project_acronym') or '—'}"
        )

    lines.extend([
        "",
        "----------------------------------------",
        f"Accedi all'app: {app_url}",
        "----------------------------------------",
        "",
        "— MAIC LAB Task Manager",
        "Università della Calabria",
    ])

    subject = f"[MAIC LAB] Riepilogo settimanale — {today.strftime('%Y/%m/%d')}"
    body = "\n".join(lines)
    return _send(subject, body, to_email)


def send_overdue_alert(task: dict, to_email: str) -> bool:
    """Send the one-shot alert when a task becomes overdue."""
    if not to_email:
        return False

    cfg = _get_settings()
    app_url = cfg.get("app_url", "http://localhost:8501")
    seq_id = _sequence_label(task)
    task_name = task.get("name", "")
    project_name = task.get("project_name") or task.get("project_acronym") or ""
    deadline = _fmt_date_slash(task.get("deadline"))
    status = task.get("status") or "—"

    subject = f"[MAIC LAB] Task scaduto: {seq_id} — {task_name}"
    body = (
        "Il task seguente è scaduto ieri e non risulta completato.\n\n"
        f"Task: {seq_id} — {task_name}\n"
        f"Progetto: {project_name}\n"
        f"Scadenza: {deadline}\n"
        f"Status attuale: {status}\n\n"
        f"Aggiorna lo status sull'app: {app_url}\n\n"
        "— MAIC LAB Task Manager"
    )
    return _send(subject, body, to_email)
