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
