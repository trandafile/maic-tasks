# MAIC LAB Task Manager - Project Specifications (As-Built)

This document reflects the current implementation in this repository.
Stack: Python, Streamlit, Supabase (PostgreSQL), ReportLab, gspread.

---

## 1. Access and Roles (RBAC)

Global roles:
- admin
- user

Task-level responsibility:
- owner
- supervisor

Current access model:
- Users authenticate with Google OAuth 2.0.
- If Google OAuth secrets are missing, a local mock login fallback is available for development.
- No auto-registration: a user must already exist in table users.
- User must be approved (is_approved = true) to enter the app.
- Admin has global visibility and access to Admin Panel.
- Non-admin users see and interact with items where they are owner or supervisor.

---

## 2. Application Structure

Entry point:
- app.py

Main views:
- views/dashboard.py
- views/projects.py
- views/calendar.py
- views/reports.py
- views/admin.py

Core modules:
- core/auth.py
- core/supabase_client.py
- db.py

Utilities:
- utils/modals.py
- utils/pdf_generator.py
- utils/helpers.py
- utils/notifications.py
- utils/scheduler.py
- utils/sync_to_sheets.py

---

## 3. Database Model (Supabase)

Status values used across tasks/subtasks:
- Not started
- Working on
- Blocked
- Completed
- Cancelled

### 3.1 Core tables

users
- email TEXT PRIMARY KEY
- name TEXT NOT NULL
- role TEXT (admin|user)
- is_approved BOOLEAN
- avatar_color TEXT

settings
- id INTEGER/SERIAL PRIMARY KEY
- expiring_threshold_days INTEGER (default 7)
- deliverable_types JSONB/TEXT depending on migration state

projects
- id INTEGER/SERIAL PRIMARY KEY
- name TEXT NOT NULL
- acronym TEXT
- identifier TEXT
- funding_agency TEXT
- start_date DATE
- end_date DATE
- is_archived BOOLEAN

deliverables
- id INTEGER/SERIAL PRIMARY KEY
- project_id FK -> projects.id
- name TEXT
- type TEXT
- status TEXT
- deadline DATE
- is_archived BOOLEAN
- description TEXT (required by current UI/report flow)

tasks
- id INTEGER/SERIAL PRIMARY KEY
- sequence_id TEXT
- project_id FK -> projects.id
- deliverable_id FK -> deliverables.id (nullable)
- name TEXT NOT NULL
- owner_email FK -> users.email
- supervisor_email FK -> users.email
- status TEXT
- priority TEXT (none|low|medium|high|urgent)
- estimate_hours REAL
- deadline DATE
- completion_date DATE
- notes TEXT
- sort_order INTEGER
- is_archived BOOLEAN
- last_reminder_sent DATE (used by scheduler)

subtasks
- id INTEGER/SERIAL PRIMARY KEY
- task_id FK -> tasks.id
- name TEXT NOT NULL
- owner_email FK -> users.email
- supervisor_email FK -> users.email
- status TEXT
- deadline DATE
- notes TEXT
- sort_order INTEGER
- is_archived BOOLEAN
- last_reminder_sent DATE (used by scheduler)

labels
- id INTEGER/SERIAL PRIMARY KEY
- name TEXT
- color TEXT

task_labels
- task_id FK -> tasks.id
- label_id FK -> labels.id
- PRIMARY KEY(task_id, label_id)

task_dependencies
- task_id FK -> tasks.id
- depends_on_task_id FK -> tasks.id
- type TEXT
- PRIMARY KEY(task_id, depends_on_task_id)

comments
- id INTEGER/SERIAL PRIMARY KEY
- task_id FK -> tasks.id
- author_email FK -> users.email
- body TEXT
- created_at TIMESTAMP
- is_system_event BOOLEAN

### 3.2 Additional settings columns currently used

The admin/settings, notifications, and scheduler modules expect these settings columns:
- smtp_host TEXT
- smtp_port INTEGER
- smtp_user TEXT
- smtp_password TEXT
- smtp_from_name TEXT
- notifications_enabled BOOLEAN
- app_url TEXT

Migration SQL is maintained in db.py (SETTINGS_MIGRATION_SQL and DELIVERABLES_MIGRATION_SQL).

---

## 4. Functional Areas

### 4.1 Dashboard

Current behavior:
- Two operational views: To Do and To Review.
- Grouping by deadline urgency: overdue, due soon (threshold from settings), upcoming.
- Flat actionable list with task/subtask detail modal actions.
- Owner/supervisor pills and status/priority badges.

### 4.2 Projects View

Current behavior:
- Project hierarchy: Deliverable -> Task -> Subtask.
- Create/edit/archive flows for projects, deliverables, tasks, subtasks.
- Task sequence_id generation based on project identifier.
- Inline detail modals and status/priority badges.
- Notes/description in markdown fields.
- Assignment notifications on create/update events (via SMTP settings).

### 4.3 Calendar View

Current behavior:
- Uses streamlit-calendar.
- Events from deliverables, tasks, subtasks (deadline-based).
- Filters by project and person (owner or supervisor).
- ICS export available.

### 4.4 Reports View

Current behavior:
- Admin tabs:
  - Project Report
  - Workload by Person
  - Staff by Project
  - Detailed Report
- Non-admin sees Project Report only.
- PDF exports implemented.
- Detailed Report supports Markdown export.
- Detailed report includes comments/activity rendering and markdown notes/description.

### 4.5 Admin Panel

Current tabs:
- Users
- Projects
- Archive
- Settings and Notifications

Capabilities:
- User management (approve, role switch, edit, delete).
- Project management (edit/delete).
- Archive management with restore and permanent delete actions.
- SMTP and notification settings save/test.
- SQL migration helper display.
- Manual backup trigger to Google Sheets (via utils/sync_to_sheets.py).

---

## 5. Notifications and Scheduler

Notifications:
- SMTP send logic in utils/notifications.py.
- Controlled by settings.notifications_enabled and smtp_password presence.
- Supports assignment, upcoming deadline, overdue, and test email.

Scheduler:
- utils/scheduler.py executed once per session after login from app.py.
- Checks tasks/subtasks deadlines and sends reminders.
- Uses last_reminder_sent to avoid duplicate daily notifications.

---

## 6. Google Sheets Backup

Module:
- utils/sync_to_sheets.py

Current behavior:
- Reads Supabase and Google service account credentials from Streamlit secrets.
- Requires GOOGLE_SHEET_BACKUP_ID in secrets.
- Sync target tabs:
  - users
  - projects
  - deliverables
  - tasks
  - subtasks
  - labels
  - task_labels
  - task_dependencies
  - comments
  - settings
- For each table: clear worksheet then upload full content snapshot.

---

## 7. Operational Notes

- Primary persistence target is Supabase (PostgreSQL).
- is_archived is used extensively for soft-hide in active views.
- Some admin actions still perform hard delete (cascade helpers in db.py).
- Keep secrets out of repository (.streamlit/secrets.toml and OAuth client secrets file are ignored).
- Requirements are defined in requirements.txt and used in Streamlit Cloud deployment.
