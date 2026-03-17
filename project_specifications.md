# MAIC LAB Task Manager — Specifiche v2.0
> Stack: Python + Streamlit + Supabase (PostgreSQL) · Ispirato a Plane.so

**Legenda:** ✅ invariato · 🔵 modificato · 🟢 nuovo da Plane.so

---

## PARTE 1 — Ruoli (RBAC)

**Ruoli:** `admin` e `user`. Supervisor è un ruolo per-task, non globale.

**Permessi `user`** ✅ — Può creare task/subtask. Interagisce pienamente solo con i task in cui è Owner o Supervisor.

**Permessi `admin`** ✅ — Visibilità e modifica globale. Approva nuovi utenti. Definisce soglia scadenze. Modifica tipi Deliverable. 🟢 Gestisce le **labels globali** (es. "simulazione", "scrittura", "misure").

🟢 **Avatar color** — ogni user ha un `avatar_color` hex generato al signup per identificazione visiva rapida.

---

## PARTE 2 — Schema Database (Supabase / PostgreSQL)

> L'app verrà ospitata su Streamlit Community Cloud (ambiente effimero). Pertanto, il database deve essere **Supabase (PostgreSQL)**, accessibile tramite API. 
> Normalizzazione obbligatoria. Non cancellare record: usare `is_archived`.
> Status fissi: `Not started` | `Working on` | `Blocked` | `Completed` | `Cancelled`

### `users` 🔵

| Campo | Tipo | Note |
|---|---|---|
| `email` | TEXT PK | |
| `name` | TEXT NOT NULL | |
| `role` | TEXT | `admin` \| `user` |
| `is_approved` | BOOLEAN | |
| `avatar_color` 🟢 | TEXT | Hex generato al signup |

### `settings` ✅

| Campo | Tipo | Note |
|---|---|---|
| `id` | INTEGER PK | |
| `expiring_threshold_days` | INTEGER | Default: 7 |
| `deliverable_types` | TEXT | JSON list |

### `projects` 🔵

| Campo | Tipo | Note |
|---|---|---|
| `id` | INTEGER PK | |
| `name` | TEXT NOT NULL | |
| `acronym` | TEXT | |
| `identifier` 🟢 | TEXT | Prefisso sequence ID (es. `MAIC`) |
| `funding_agency` | TEXT | |
| `start_date`, `end_date` | DATE | |
| `is_archived` | BOOLEAN | |

### `deliverables` ✅

| Campo | Tipo | Note |
|---|---|---|
| `id` | INTEGER PK | |
| `project_id` | FK → projects | |
| `name` | TEXT | |
| `type` | TEXT | `paper` \| `layout` \| `prototype` |
| `status` | TEXT | |
| `deadline` | DATE | |
| `is_archived` | BOOLEAN | |

### `tasks` 🔵

| Campo | Tipo | Note |
|---|---|---|
| `id` | INTEGER PK | |
| `sequence_id` 🟢 | TEXT | Auto-generato es. `MAIC-42` |
| `project_id` | FK → projects | |
| `deliverable_id` | FK → deliverables | Nullable |
| `name` | TEXT NOT NULL | |
| `owner_email` | FK → users | |
| `supervisor_email` | FK → users | |
| `status` | TEXT | 5 valori fissi |
| `priority` 🟢 | TEXT | `none\|low\|medium\|high\|urgent` |
| `estimate_hours` 🟢 | REAL | Nullable |
| `deadline` | DATE | |
| `completion_date` | DATE | |
| `notes` | TEXT | Markdown |
| `sort_order` | INTEGER | |
| `is_archived` | BOOLEAN | |

### `subtasks` ✅

| Campo | Tipo | Note |
|---|---|---|
| `id` | INTEGER PK | |
| `task_id` | FK → tasks | |
| `name` | TEXT NOT NULL | |
| `owner_email`, `supervisor_email` | FK → users | |
| `status` | TEXT | 5 valori fissi |
| `deadline` | DATE | |
| `notes` | TEXT | Markdown |
| `sort_order` | INTEGER | |
| `is_archived` | BOOLEAN | |

### `labels` 🟢

| Campo | Tipo | Note |
|---|---|---|
| `id` | INTEGER PK | |
| `name` | TEXT | es. "simulazione" |
| `color` | TEXT | Hex |

### `task_labels` 🟢 (ponte task ↔ labels)

| Campo | Tipo |
|---|---|
| `task_id` | FK → tasks |
| `label_id` | FK → labels |

### `task_dependencies` 🟢

| Campo | Tipo | Note |
|---|---|---|
| `task_id` | FK → tasks | |
| `depends_on_task_id` | FK → tasks | |
| `type` | TEXT | `blocks` \| `relates_to` |

### `comments` 🟢

| Campo | Tipo | Note |
|---|---|---|
| `id` | INTEGER PK | |
| `task_id` | FK → tasks | |
| `author_email` | FK → users | |
| `body` | TEXT | Markdown |
| `created_at` | DATETIME | |
| `is_system_event` | BOOLEAN | `1` = log automatico |

---

## PARTE 3 — Interfaccia Streamlit

### 3.1 Dashboard Personale ✅
Task in scadenza/scaduti (Owner o Supervisor). Pulsante "Vai a tutti i miei Task".

### 3.2 Project View 🔵
- `st.expander` per progetto → albero `Deliverable → Task → SubTask`
- Task altrui in grigio chiaro
- Azioni inline: cambio Status, "View details" (modal con note MD + activity feed), "Archivia"
- Pulsante aggiunta rapida task/subtask in fondo ad ogni progetto espanso
- Ordinamento Su/Giù per `sort_order`
- 🟢 **Priority badge** colorato inline (grigio/blu/arancio/rosso)
- 🟢 **Sequence ID** es. `MAIC-42` sempre visibile in grigio
- 🟢 **Dependencies indicator**: badge "bloccato da MAIC-38" se attivo
- 🟢 **Labels filter** in toolbar per vista cross-progetto

### 3.3 Vista Calendario ✅
Componente `streamlit-calendar` con deadline di Task, Subtask e Deliverable.

### 3.4 Activity Feed nel dettaglio task 🟢
- Commenti manuali (Owner, Supervisor, Admin) in Markdown
- Log automatici: cambio stato, modifica deadline, riassegnazione

### 3.5 Reportistica PDF e markdown ✅
Per questi report prevedi la possibilità di esportare sia in formato pdf che markdown: 
- Report attività globali/archiviate
- "Chi lavora in cosa" (per Progetto)
- "Attività per persona"
- Vista Deliverables (Paper, Prototype, Layout)

### 3.6 Pannello Admin ✅ + 🔵
- Gestione utenti (`is_approved`, ruolo)
- Impostazioni (soglia scadenze, tipi deliverable)
- 🟢 Gestione Labels (crea, modifica, elimina)

---

## PARTE 4 — Note Implementative

### Struttura file consigliata
```text
maic_taskmanager/
├── app.py
├── core/
│   ├── supabase_client.py
│   ├── auth.py
│   └── models.py
├── views/
│   ├── dashboard.py
│   ├── projects.py
│   ├── calendar.py
│   ├── reports.py
│   └── admin.py
└── utils/
    ├── pdf_generator.py   # reportlab
    └── notifications.py   # smtplib