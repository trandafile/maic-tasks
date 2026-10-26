"""utils/task_import.py — import deliverables, tasks and subtasks into ONE
project from a pasted YAML or JSON payload (schema maic-tasks-import/v1).

    parse_payload()  text -> data
    validate()       data + snapshot of the project -> Plan (writes nothing)
    apply_plan()     Plan -> database (numbers already assigned by validate)

Rules
* Everything lives in the project the import was opened from; refs carry its
  letter (E.1, E.1.2, E.1.2.1; E.0 holds the tasks without a deliverable).
* Existing items are named by ``ref`` and confirmed by ``match_title``; a
  mismatch makes the file invalid rather than touching the wrong item.
* People are written as names and resolved against the team; an ambiguous
  or unknown name makes the file invalid.
* New items get the first free number of their parent (archived ones count),
  like the Add dialogs. A moved task keeps its number when it is free there.
* Nothing is ever deleted: ``cancel`` sets the status to Cancelled.
* Duplicates: an item referenced twice, two creates with the same title under
  the same parent, or a create whose title already exists there make the
  file invalid (unless ``allow_duplicates``), so pasting the same file twice
  does not double the work.
"""

from __future__ import annotations

import datetime as _dt
import difflib
import json
import re
import unicodedata

SCHEMA_ID = "maic-tasks-import/v1"
STATUSES = ["Not started", "Working on", "Blocked", "Completed", "Cancelled"]
PRIORITIES = ["none", "low", "medium", "high", "urgent"]
CLOSED = ("Completed", "Cancelled")

_STATUS_ALIASES = {
    "not started": "Not started", "todo": "Not started", "to do": "Not started",
    "open": "Not started", "new": "Not started", "planned": "Not started",
    "working on": "Working on", "in progress": "Working on", "working": "Working on",
    "ongoing": "Working on", "wip": "Working on", "started": "Working on",
    "blocked": "Blocked", "on hold": "Blocked",
    "completed": "Completed", "complete": "Completed", "done": "Completed",
    "closed": "Completed", "finished": "Completed",
    "cancelled": "Cancelled", "canceled": "Cancelled", "dropped": "Cancelled",
}
_PRIORITY_ALIASES = {"normal": "medium", "med": "medium", "critical": "urgent",
                     "highest": "urgent", "lowest": "low", "": "none"}

ACTIONS = {
    "deliverable": ("create", "update", "complete", "cancel", "keep"),
    "task": ("create", "update", "move", "complete", "cancel", "keep"),
    "subtask": ("create", "update", "move", "complete", "cancel", "keep"),
}
_COMMON = {"action", "ref", "key", "match_title", "from", "title", "status", "due",
           "supervisor", "description", "description_append"}
KEYS = {
    "deliverable": _COMMON | {"type", "owner", "tasks"},
    "task": _COMMON | {"priority", "assignee", "subtasks"},
    "subtask": _COMMON | {"assignee"},
}
_FIELD_KEYS = {"title", "type", "status", "owner", "assignee", "supervisor", "due",
               "priority", "description", "description_append"}
TOP_KEYS = {"schema", "project", "defaults", "deliverables"}
DEFAULT_KEYS = {"supervisor", "status", "priority", "subtask_assignee", "owner"}

TITLE_MATCH = 0.85      # match_title vs the real title
DUP_MATCH = 0.90        # a create that looks like an existing sibling


# ── text helpers ──────────────────────────────────────────────────────────────

def _norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^\w]+", " ", s.casefold())
    return " ".join(s.split())


def similarity(a, b) -> float:
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def _fmt_date(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        return _dt.date.fromisoformat(str(iso)[:10]).strftime("%d/%m/%Y")
    except ValueError:
        return str(iso)


# ── parsing ───────────────────────────────────────────────────────────────────

def parse_payload(text: str):
    """(data, error). JSON when it looks like JSON, YAML otherwise."""
    text = (text or "").strip()
    if not text:
        return None, "Paste a YAML or JSON payload first."
    # Code fences copied from a chat are tolerated.
    fence = re.match(r"^```[\w-]*\s*\n(.*?)\n```\s*$", text, re.S)
    if fence:
        text = fence.group(1)
    if text[:1] in "{[":
        try:
            return json.loads(text), None
        except json.JSONDecodeError as exc:
            return None, f"Invalid JSON (line {exc.lineno}, column {exc.colno}): {exc.msg}."
    try:
        import yaml
    except ImportError:
        return None, "YAML support is not installed on the server (pyyaml): paste JSON instead."
    try:
        return yaml.safe_load(text), None
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f" (line {mark.line + 1}, column {mark.column + 1})" if mark else ""
        problem = getattr(exc, "problem", None) or str(exc).splitlines()[0]
        return None, f"Invalid YAML{where}: {problem}."


# ── people ────────────────────────────────────────────────────────────────────

class People:
    """Names written in the payload -> e-mails of approved users."""

    def __init__(self, users: list[dict], me: str | None = None):
        self.users = [u for u in (users or []) if u.get("email")]
        self.me = me
        self._by_email = {u["email"].casefold(): u for u in self.users}

    def name(self, email: str | None) -> str:
        if not email:
            return "—"
        u = self._by_email.get(email.casefold())
        return (u.get("name") or email) if u else email

    def _tokens(self, u: dict) -> list[str]:
        local = u["email"].split("@")[0]
        return _norm(u.get("name")).split() + _norm(local.replace(".", " ")).split()

    def resolve(self, text):
        """(email, error, note). note says how a short or misspelt name was read."""
        raw = str(text or "").strip()
        if not raw:
            return None, "empty name", None
        if raw.casefold() in ("me", "myself"):
            return self.me, None, None
        if "@" in raw:
            u = self._by_email.get(raw.casefold())
            if u:
                return u["email"], None, None
            return None, f"'{raw}': no team member has this e-mail", None
        q = _norm(raw)
        exact = [u for u in self.users if _norm(u.get("name")) == q]
        if len(exact) == 1:
            return exact[0]["email"], None, None
        qt = q.split()
        cands = [u for u in self.users
                 if all(any(nt.startswith(t) for nt in self._tokens(u)) for t in qt)]
        if len(cands) == 1:
            return cands[0]["email"], None, f"'{raw}' → {cands[0].get('name')}"
        if len(cands) > 1:
            names = ", ".join(sorted(u.get("name") or u["email"] for u in cands))
            return None, f"'{raw}' is ambiguous ({names}): write the full name", None
        # Misspellings: every word must be close to a word of the same person.
        fuzzy = [u for u in self.users
                 if all(any(difflib.SequenceMatcher(None, t, nt).ratio() >= 0.8
                            for nt in self._tokens(u)) for t in qt)]
        if len(fuzzy) == 1:
            return fuzzy[0]["email"], None, f"'{raw}' → {fuzzy[0].get('name')} (approximate)"
        if len(fuzzy) > 1:
            names = ", ".join(sorted(u.get("name") or u["email"] for u in fuzzy))
            return None, f"'{raw}' is ambiguous ({names}): write the full name", None
        near = difflib.get_close_matches(raw, [u.get("name") or "" for u in self.users], n=3, cutoff=0.5)
        hint = f" — did you mean {', '.join(near)}?" if near else ""
        return None, f"'{raw}': no team member with this name{hint}", None


# ── the plan ──────────────────────────────────────────────────────────────────

class Op:
    """One change. ``parent`` is the deliverable Op of a task (the E.0 Op for
    tasks without one) or the task Op of a subtask."""

    def __init__(self, kind, action, row=None, parent=None, label=""):
        self.kind, self.action, self.row, self.parent = kind, action, row, parent
        self.label = label
        self.no: int | None = (row or {}).get("code_no")
        self.fields: dict = {}          # columns to write (all of them for a create)
        self.changes: list[tuple[str, str, str]] = []
        self.loose = False              # the E.0 container
        self.complete = False           # deliverable: sign off at the end
        self.old_code: str | None = None
        self.key: str | None = None
        self.notes: list[str] = []

    @property
    def final(self) -> dict:
        return {**(self.row or {}), **self.fields}

    @property
    def title(self) -> str:
        return self.final.get("name") or ""

    @property
    def ident(self):
        if self.loose:
            return ("loose",)
        return ("id", self.row["id"]) if self.row else ("new", id(self))

    def code(self, letter: str) -> str:
        if self.loose:
            return f"{letter}.0"
        chain, op = [], self
        while op is not None:
            chain.append(0 if op.loose else op.no)
            op = op.parent
        if any(n is None for n in chain):
            return ""
        return ".".join([letter] + [str(n) for n in reversed(chain)])


class Plan:
    def __init__(self):
        self.ops: list[Op] = []
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.notes: list[str] = []      # how names were resolved

    @property
    def ok(self) -> bool:
        return not self.errors

    def changes(self) -> list[Op]:
        return [o for o in self.ops if not o.loose and (o.action != "keep" or o.fields)]

    def counts(self) -> dict:
        out: dict = {}
        for o in self.changes():
            out[(o.kind, o.action)] = out.get((o.kind, o.action), 0) + 1
        return out


# ── snapshot ──────────────────────────────────────────────────────────────────

def load_snapshot(project_id: int) -> dict:
    """Every deliverable, task and subtask of the project, archived included
    (archived numbers stay taken)."""
    from core.supabase_client import supabase
    ds = supabase.table("deliverables").select("*").eq("project_id", project_id).execute().data or []
    ts = supabase.table("tasks").select("*").eq("project_id", project_id).execute().data or []
    ss = []
    ids = [t["id"] for t in ts]
    for i in range(0, len(ids), 150):
        ss += supabase.table("subtasks").select("*").in_("task_id", ids[i:i + 150]).execute().data or []
    return {"deliverables": ds, "tasks": ts, "subtasks": ss}


# ── validation ────────────────────────────────────────────────────────────────

def _status(v):
    if v is None:
        return None, "status is empty"
    s = _STATUS_ALIASES.get(_norm(v).replace("_", " "))
    if s:
        return s, None
    return None, f"status '{v}' is not valid ({', '.join(STATUSES)})"


def _priority(v):
    p = _norm(v)
    p = _PRIORITY_ALIASES.get(p, p)
    if p in PRIORITIES:
        return p, None
    return None, f"priority '{v}' is not valid ({', '.join(PRIORITIES)})"


def _date(v):
    """(iso | None, error). None/'' clears the date."""
    if v is None or (isinstance(v, str) and not v.strip()):
        return None, None
    if isinstance(v, _dt.datetime):
        v = v.date()
    if isinstance(v, _dt.date):
        return v.isoformat(), None
    s = str(v).strip()
    for f in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return _dt.datetime.strptime(s, f).date().isoformat(), None
        except ValueError:
            pass
    return None, f"date '{v}' is not valid (use YYYY-MM-DD)"


def validate(data, project: dict, snap: dict, users: list[dict], me: str | None,
             type_options: list[str] | None = None, allow_duplicates: bool = False) -> Plan:
    plan = Plan()
    E, W = plan.errors.append, plan.warnings.append
    people = People(users, me)
    types = [t for t in (type_options or []) if t] or ["paper", "layout", "prototype"]
    letter = (project.get("code_letter") or "").strip().upper()
    pid = project.get("id")

    if not isinstance(data, dict):
        E("The payload must be a mapping with schema, project, defaults and deliverables.")
        return plan
    for k in data:
        if k not in TOP_KEYS:
            E(f"Unknown top-level key '{k}' (allowed: {', '.join(sorted(TOP_KEYS))}).")
    schema = data.get("schema")
    if schema is None:
        W(f"No 'schema' line: read as {SCHEMA_ID}.")
    elif str(schema).strip() != SCHEMA_ID:
        E(f"schema '{schema}' is not supported (expected {SCHEMA_ID}).")
    if not letter:
        E("This project has no letter yet: assign one (Admin panel → project letters) before importing.")
        return plan

    # ── the project: everything must belong to the one the import was opened from
    proj = data.get("project")
    acr, pname = project.get("acronym") or "", project.get("name") or ""
    if not isinstance(proj, dict) or not (proj.get("code") or proj.get("name")):
        E("'project' must give the code (letter) and/or the name of this project.")
    else:
        code = str(proj.get("code") or "").strip()
        if code and code.upper() != letter and _norm(code) not in (_norm(acr), _norm(pname)):
            E(f"project.code '{code}' is not this project ({letter} · {acr or pname}): "
              f"an import only touches the project it is opened from.")
        name = proj.get("name")
        if name and max(similarity(name, acr), similarity(name, pname),
                        similarity(name, f"{acr} {pname}")) < TITLE_MATCH \
                and _norm(name) not in _norm(f"{acr} {pname}"):
            E(f"project.name '{name}' does not match this project ({acr} · {pname}).")

    # ── defaults
    dfl = data.get("defaults") or {}
    if not isinstance(dfl, dict):
        E("'defaults' must be a mapping.")
        dfl = {}
    for k in dfl:
        if k not in DEFAULT_KEYS:
            E(f"defaults: unknown key '{k}' (allowed: {', '.join(sorted(DEFAULT_KEYS))}).")

    def person(value, where, allow_none=False):
        if value is None or (allow_none and _norm(value) in ("none", "nobody", "")):
            return None
        email, err, note = people.resolve(value)
        if err:
            E(f"{where}: {err}.")
            return None
        if note and note not in plan.notes:
            plan.notes.append(note)
        return email

    d_sup = person(dfl.get("supervisor"), "defaults.supervisor", allow_none=True)
    d_owner = person(dfl.get("owner"), "defaults.owner") if dfl.get("owner") else me
    d_status = "Not started"
    if dfl.get("status") is not None:
        d_status, err = _status(dfl.get("status"))
        if err:
            E(f"defaults: {err}.")
            d_status = "Not started"
    d_priority = "medium"
    if dfl.get("priority") is not None:
        d_priority, err = _priority(dfl.get("priority"))
        if err:
            E(f"defaults: {err}.")
            d_priority = "medium"
    sub_inherit, sub_default = True, None
    sa = dfl.get("subtask_assignee", "inherit")
    if sa is not None and _norm(sa) != "inherit":
        sub_inherit, sub_default = False, person(sa, "defaults.subtask_assignee")

    # ── what exists
    ds, ts, ss = snap.get("deliverables", []), snap.get("tasks", []), snap.get("subtasks", [])
    dno = {d["id"]: d.get("code_no") for d in ds}
    t_by_id = {t["id"]: t for t in ts}

    def tcode(t):
        n = dno.get(t.get("deliverable_id")) if t.get("deliverable_id") else 0
        return f"{letter}.{n}.{t.get('code_no')}" if n is not None and t.get("code_no") is not None else None

    def scode(s):
        t = t_by_id.get(s.get("task_id"))
        c = tcode(t) if t else None
        return f"{c}.{s.get('code_no')}" if c and s.get("code_no") is not None else None

    d_codes = {f"{letter}.{d['code_no']}": d for d in ds if d.get("code_no") is not None}
    t_codes = {c: t for t in ts if (c := tcode(t))}
    s_codes = {c: s for s in ss if (c := scode(s))}
    used_d = {d["code_no"] for d in ds if d.get("code_no") is not None}
    used_t: dict = {}
    for t in ts:
        if t.get("code_no") is not None:
            used_t.setdefault(("id", t["deliverable_id"]) if t.get("deliverable_id") else ("loose",),
                              set()).add(t["code_no"])
    used_s: dict = {}
    for s in ss:
        if s.get("code_no") is not None:
            used_s.setdefault(("id", s["task_id"]), set()).add(s["code_no"])

    def take(used: set, keep: int | None = None) -> int:
        n = keep if keep is not None and keep not in used else ((max(used) + 1) if used else 1)
        used.add(n)
        return n

    touched: dict = {}                   # (table, id) -> where it was referenced
    keys_seen: dict = {}
    created_titles: dict = {}            # parent ident -> [(norm title, where)]

    # ── one entry (deliverable, task or subtask) ─────────────────────────────
    def entry_op(kind, e, where, parent: Op | None):
        if not isinstance(e, dict):
            E(f"{where}: must be a mapping.")
            return None
        for k in e:
            if k not in KEYS[kind]:
                E(f"{where}: unknown key '{k}'.")
        if e.get("key") is not None:
            kk = str(e["key"]).strip()
            if kk in keys_seen:
                E(f"{where}: key '{kk}' is already used at {keys_seen[kk]}.")
            keys_seen[kk] = where
        ref = str(e["ref"]).strip().upper() if e.get("ref") not in (None, "") else None
        frm = str(e["from"]).strip().upper() if e.get("from") not in (None, "") else None
        action = str(e.get("action") or "").strip().lower()
        if not action:
            if ref or frm or e.get("match_title"):
                E(f"{where}: 'action' is missing (existing items need update, move, complete, cancel or keep).")
                return None
            action = "create"
        if action not in ACTIONS[kind]:
            E(f"{where}: action '{action}' is not valid for a {kind} ({', '.join(ACTIONS[kind])}).")
            return None

        # the E.0 container
        if kind == "deliverable" and ref == f"{letter}.0":
            if action != "keep":
                E(f"{where}: {letter}.0 (tasks without deliverable) only takes action: keep.")
            extra = sorted(k for k in e if k in _FIELD_KEYS)
            if extra:
                E(f"{where}: {letter}.0 has no fields to change ({', '.join(extra)}).")
            op = Op(kind, "keep", None, None, where)
            op.loose, op.no = True, 0
            return op

        if ref and not ref.startswith(letter + "."):
            E(f"{where}: ref {ref} belongs to another project (this one is {letter}).")
            return None
        if frm and not frm.startswith(letter + "."):
            E(f"{where}: from {frm} belongs to another project (this one is {letter}); "
              f"items cannot be moved between projects.")
            return None
        if frm and action != "move":
            E(f"{where}: 'from' is only used with action: move.")
            return None

        if action == "create":
            if ref:
                E(f"{where}: a create takes no ref — numbers are assigned automatically.")
                return None
            title = str(e.get("title") or "").strip()
            if not title:
                E(f"{where}: title is required to create a {kind}.")
                return None
            op = Op(kind, "create", None, parent, where)
            op.key = e.get("key")
            # duplicates: in the file, then among the existing siblings
            pkey = parent.ident if parent else ("project",)
            mine = created_titles.setdefault((kind, pkey), [])
            for nt, w in mine:
                if similarity(nt, title) >= DUP_MATCH:
                    E(f"{where}: '{title}' is created twice under the same parent (also at {w}).")
            mine.append((title, where))
            for sib_code, sib in siblings(kind, parent):
                if similarity(sib.get("name"), title) >= DUP_MATCH:
                    msg = (f"{where}: '{title}' already exists as {sib_code} '{sib.get('name')}' — "
                           f"use action update/keep with ref: {sib_code}")
                    (W if allow_duplicates else E)(msg + (" (created anyway)." if allow_duplicates else "."))
            return op

        # an existing item
        title_hint = e.get("match_title")
        if not title_hint:
            E(f"{where}: match_title is required for existing items (it confirms the ref).")
            return None
        code = frm if action == "move" else ref
        if action == "move" and not frm:
            E(f"{where}: move needs 'from' (the current code, e.g. {letter}.1.2).")
            return None
        if action == "move" and ref:
            E(f"{where}: a move takes 'from', not 'ref': the new number is assigned automatically.")
            return None
        table = {"deliverable": d_codes, "task": t_codes, "subtask": s_codes}[kind]
        if code:
            row = table.get(code)
            if row is None:
                E(f"{where}: {code} does not exist in this project.")
                return None
        else:
            # no ref: the title alone, among the siblings
            cands = [(c, r) for c, r in siblings(kind, parent)
                     if similarity(r.get("name"), title_hint) >= TITLE_MATCH]
            if not cands:
                E(f"{where}: no {kind} titled '{title_hint}' here — give its ref.")
                return None
            if len(cands) > 1:
                E(f"{where}: '{title_hint}' matches {', '.join(c for c, _ in cands)} — give the ref.")
                return None
            code, row = cands[0]
        if row.get("is_archived"):
            E(f"{where}: {code} is archived and cannot be changed by an import.")
            return None
        if title_hint is not None:
            sc = similarity(row.get("name"), title_hint)
            if sc < TITLE_MATCH:
                E(f"{where}: {code} is '{row.get('name')}', not '{title_hint}' (match_title).")
                return None
            if sc < 1.0:
                W(f"{where}: match_title '{title_hint}' taken as {code} '{row.get('name')}'.")
        tkey = (kind, row["id"])
        if tkey in touched:
            E(f"{where}: {code} is already referenced at {touched[tkey]} — one entry per item.")
            return None
        touched[tkey] = where
        op = Op(kind, action, row, parent, where)
        op.key = e.get("key")
        op.old_code = code
        if kind == "deliverable":
            return op
        # must sit under its current parent, unless moved
        cur_parent = (("id", row["deliverable_id"]) if row.get("deliverable_id") else ("loose",)) \
            if kind == "task" else ("id", row["task_id"])
        if action == "move":
            if parent and parent.ident == cur_parent:
                E(f"{where}: {code} is already under {parent.code(letter)} — nothing to move.")
                return None
        elif parent and parent.ident != cur_parent:
            E(f"{where}: {code} is not under {parent.code(letter) or 'this ' + ('deliverable' if kind == 'task' else 'task')}"
              f" — to move it use action: move, from: {code}.")
            return None
        return op

    def siblings(kind, parent):
        """[(code, row)] of the active items currently under ``parent``."""
        if kind == "deliverable":
            return [(c, r) for c, r in d_codes.items() if not r.get("is_archived")]
        if parent is None or (parent.row is None and not parent.loose):
            return []
        if kind == "task":
            pid_ = None if parent.loose else parent.row["id"]
            return [(c, r) for c, r in t_codes.items()
                    if not r.get("is_archived") and r.get("deliverable_id") == pid_]
        return [(c, r) for c, r in s_codes.items()
                if not r.get("is_archived") and r.get("task_id") == parent.row["id"]]

    # ── field changes of one entry ───────────────────────────────────────────
    def fields_of(op: Op, e: dict, where: str):
        kind, row = op.kind, op.row or {}
        create = op.action == "create"
        out: dict = {}
        ch = op.changes

        def put(col, new, label, show=lambda v: v if v not in (None, "") else "—"):
            old = row.get(col)
            if create:
                out[col] = new
            elif (old or None) != (new or None):
                out[col] = new
                ch.append((label, str(show(old)), str(show(new))))

        if op.action == "keep":
            extra = sorted(k for k in e if k in _FIELD_KEYS)
            if extra:
                E(f"{where}: keep changes nothing ({', '.join(extra)} given) — use update.")
            return
        if "title" in e and str(e.get("title") or "").strip():
            put("name", str(e["title"]).strip(), "title")
        elif "title" in e and not create:
            E(f"{where}: title cannot be empty.")

        if kind == "deliverable" and ("type" in e or create):
            raw = e.get("type")
            if raw is None:
                if create:
                    put("type", types[0], "type")
                    W(f"{where}: no type given — '{types[0]}' used.")
            else:
                hit = next((t for t in types if _norm(t) == _norm(raw)), None)
                if hit:
                    put("type", hit, "type")
                else:
                    E(f"{where}: type '{raw}' is not valid ({', '.join(types)}).")

        # status: explicit, from the action, or the default for a create
        status = None
        if "status" in e:
            status, err = _status(e.get("status"))
            if err:
                E(f"{where}: {err}.")
        if op.action in ("complete", "cancel"):
            forced = "Completed" if op.action == "complete" else "Cancelled"
            if status and status != forced:
                E(f"{where}: action {op.action} conflicts with status '{status}'.")
            status = forced
        if create and status is None:
            status = d_status
        if status is not None:
            if kind == "deliverable" and status == "Completed":
                if row.get("status") != "Completed":
                    op.complete = True              # signed off at the end
                    ch.append(("status", str(row.get("status") or "—") if row else "new",
                               "Completed (signed off)"))
                if create:
                    out["status"] = "Not started"
            elif kind == "deliverable" and row.get("status") == "Completed" and status != "Completed":
                E(f"{where}: {op.old_code} is signed off as Completed; reopen it in the app first.")
            else:
                put("status", status, "status")
                if kind == "task" and (create or row.get("status") != status):
                    if status == "Completed":
                        out["completion_date"] = _dt.date.today().isoformat()
                    elif row.get("status") == "Completed":
                        out["completion_date"] = None

        if kind == "task" and ("priority" in e or create):
            if e.get("priority") is not None:
                p, err = _priority(e.get("priority"))
                if err:
                    E(f"{where}: {err}.")
                else:
                    put("priority", p, "priority")
            elif create:
                put("priority", d_priority, "priority")

        # people
        who_key = "owner" if kind == "deliverable" else "assignee"
        if e.get(who_key) is not None:
            em = person(e.get(who_key), f"{where}.{who_key}")
            if em:
                put("owner_email", em, who_key, people.name)
        elif create:
            if kind == "subtask":
                em = (op.parent.final.get("owner_email") if sub_inherit and op.parent else None) \
                    or sub_default or d_owner
            else:
                em = d_owner
            put("owner_email", em, who_key, people.name)
        if "supervisor" in e:
            em = person(e.get("supervisor"), f"{where}.supervisor", allow_none=True)
            if em or _norm(e.get("supervisor")) in ("none", "nobody", ""):
                put("supervisor_email", em, "supervisor", people.name)
        elif create:
            sup = d_sup
            if kind == "subtask" and op.parent:
                sup = op.parent.final.get("supervisor_email") or d_sup
            put("supervisor_email", sup, "supervisor", people.name)

        if "due" in e:
            iso, err = _date(e.get("due"))
            if err:
                E(f"{where}: {err}.")
            else:
                put("deadline", iso, "due", _fmt_date)

        col = "description" if kind == "deliverable" else "notes"
        if "description" in e and "description_append" in e:
            E(f"{where}: give description or description_append, not both.")
        elif "description" in e:
            put(col, str(e.get("description") or "").strip() or None, "description",
                lambda v: (str(v)[:40] + "…") if v and len(str(v)) > 40 else (v or "—"))
        elif e.get("description_append"):
            add = str(e["description_append"]).strip()
            old = (row.get(col) or "").rstrip()
            out[col] = f"{old}\n\n{add}" if old else add
            if not create:
                ch.append(("description", "", f"+ {add[:40]}{'…' if len(add) > 40 else ''}"))

        op.fields.update(out)

    # ── walk ─────────────────────────────────────────────────────────────────
    delivs = data.get("deliverables")
    if not isinstance(delivs, list) or not delivs:
        E("'deliverables' must be a non-empty list.")
        return plan

    for i, de in enumerate(delivs):
        w = f"deliverables[{i + 1}]" + (f" '{de.get('title') or de.get('match_title') or de.get('ref')}'"
                                         if isinstance(de, dict) else "")
        dop = entry_op("deliverable", de, w, None)
        if dop is None:
            continue
        if not dop.loose:
            fields_of(dop, de, w)
            if dop.action == "create":
                dop.no = take(used_d)
                dop.fields["project_id"] = pid
        plan.ops.append(dop)
        tasks = de.get("tasks") or []
        if not isinstance(tasks, list):
            E(f"{w}: 'tasks' must be a list.")
            continue
        for j, te in enumerate(tasks):
            tw = f"{w} › tasks[{j + 1}]" + (f" '{te.get('title') or te.get('match_title') or te.get('from') or te.get('ref')}'"
                                            if isinstance(te, dict) else "")
            top = entry_op("task", te, tw, dop)
            if top is None:
                continue
            fields_of(top, te, tw)
            tused = used_t.setdefault(dop.ident, set())
            if top.action == "create":
                top.no = take(tused)
                top.fields.update({"project_id": pid, "sort_order": 999})
            elif top.action == "move":
                old_no = top.row.get("code_no")
                top.no = take(tused, keep=old_no)
                top.fields["code_no"] = top.no
                top.fields["code_history"] = _append_history(top.row.get("code_history"), top.old_code)
                top.changes.insert(0, ("moved from", top.old_code, ""))
            plan.ops.append(top)
            subs = te.get("subtasks") or []
            if not isinstance(subs, list):
                E(f"{tw}: 'subtasks' must be a list.")
                continue
            for k, se in enumerate(subs):
                sw = f"{tw} › subtasks[{k + 1}]" + (f" '{se.get('title') or se.get('match_title') or se.get('from') or se.get('ref')}'"
                                                   if isinstance(se, dict) else "")
                sop = entry_op("subtask", se, sw, top)
                if sop is None:
                    continue
                fields_of(sop, se, sw)
                sused = used_s.setdefault(top.ident, set())
                if sop.action == "create":
                    sop.no = take(sused)
                    sop.fields["sort_order"] = 999
                elif sop.action == "move":
                    sop.no = take(sused, keep=sop.row.get("code_no"))
                    sop.fields["code_no"] = sop.no
                    sop.fields["code_history"] = _append_history(sop.row.get("code_history"), sop.old_code)
                    sop.changes.insert(0, ("moved from", sop.old_code, ""))
                plan.ops.append(sop)

    # the numbers of the new items, for the messages below
    for op in plan.ops:
        if op.action == "create":
            op.fields["code_no"] = op.no

    _check_closures(plan, snap, letter)
    if plan.ok and not plan.changes():
        W("Nothing to change: every entry is keep or already up to date.")
    # same title elsewhere in the project: worth a look, not an error
    for op in plan.ops:
        if op.kind == "task" and op.action == "create":
            for c, r in t_codes.items():
                if not r.get("is_archived") and similarity(r.get("name"), op.title) >= DUP_MATCH \
                        and r.get("deliverable_id") != (op.parent.row or {}).get("id"):
                    W(f"{op.label}: a task with this title already exists as {c} (another deliverable).")
                    break
    return plan


def _append_history(old_history, old_code):
    if not old_code:
        return old_history
    parts = [p.strip() for p in (old_history or "").split(",") if p.strip()]
    if old_code not in parts:
        parts.append(old_code)
    return ", ".join(parts)


def _check_closures(plan: Plan, snap: dict, letter: str) -> None:
    """A deliverable cannot be completed or cancelled while any of its tasks or
    subtasks is still open — after this import. Completing a task with open
    subtasks is only a warning (the app allows it)."""
    tops = {o.row["id"]: o for o in plan.ops if o.kind == "task" and o.row}
    sops = {o.row["id"]: o for o in plan.ops if o.kind == "subtask" and o.row}

    tasks = []          # (deliverable ident, task ident, final status, name)
    for t in snap.get("tasks", []):
        if t.get("is_archived"):
            continue
        op = tops.get(t["id"])
        if op:
            continue
        d = ("id", t["deliverable_id"]) if t.get("deliverable_id") else ("loose",)
        tasks.append((d, ("id", t["id"]), t.get("status") or "Not started", t.get("name")))
    for o in plan.ops:
        if o.kind == "task":
            tasks.append((o.parent.ident, o.ident, o.final.get("status") or "Not started", o.title))
    subs = []           # (task ident, final status, name)
    for s in snap.get("subtasks", []):
        if s.get("is_archived") or s["id"] in sops:
            continue
        subs.append((("id", s["task_id"]), s.get("status") or "Not started", s.get("name")))
    for o in plan.ops:
        if o.kind == "subtask":
            subs.append((o.parent.ident, o.final.get("status") or "Not started", o.title))

    for o in plan.ops:
        if o.kind == "deliverable" and not o.loose and (o.complete or o.final.get("status") == "Cancelled"
                                                       and (o.row or {}).get("status") != "Cancelled"):
            mine = [t for t in tasks if t[0] == o.ident]
            t_ids = {t[1] for t in mine}
            open_t = [t[3] for t in mine if t[2] not in CLOSED]
            open_s = [s[2] for s in subs if s[0] in t_ids and s[1] not in CLOSED]
            if open_t or open_s:
                names = ", ".join((open_t + open_s)[:4]) + ("…" if len(open_t + open_s) > 4 else "")
                verb = "complete" if o.complete else "cancel"
                plan.errors.append(f"{o.label}: cannot {verb} {o.code(letter) or 'it'} — still open after this import: "
                  f"{len(open_t)} task(s), {len(open_s)} subtask(s) ({names}). "
                  f"Complete or cancel them in the same file.")
        if o.kind == "task" and o.final.get("status") == "Completed" and (o.row or {}).get("status") != "Completed":
            open_s = [s[2] for s in subs if s[0] == o.ident and s[1] not in CLOSED]
            if open_s:
                plan.warnings.append(f"{o.label}: completed with {len(open_s)} open subtask(s).")


# ── preview ───────────────────────────────────────────────────────────────────

ACTION_LABEL = {"create": "＋ create", "update": "✎ update", "move": "→ move",
                "complete": "✓ complete", "cancel": "✕ cancel", "keep": "· keep"}


def preview_rows(plan: Plan, letter: str, people: People) -> list[dict]:
    rows = []
    for o in plan.ops:
        if o.loose:
            rows.append({"Code": f"{letter}.0", "Action": "· keep", "Item": "Tasks without deliverable",
                         "Changes": ""})
            continue
        indent = {"deliverable": "", "task": "  ", "subtask": "      › "}[o.kind]
        f = o.final
        if o.action == "create":
            bits = [f.get("status") or "", people.name(f.get("owner_email"))]
            if f.get("supervisor_email"):
                bits.append("sup " + people.name(f.get("supervisor_email")))
            if f.get("deadline"):
                bits.append("due " + _fmt_date(f.get("deadline")))
            if o.kind == "deliverable":
                bits.insert(0, f.get("type") or "")
            if o.kind == "task" and f.get("priority"):
                bits.append(f.get("priority"))
            if o.complete:
                bits.append("→ Completed (signed off)")
            changes = " · ".join(b for b in bits if b)
        else:
            changes = "; ".join(f"{lab}: {a} → {b}" if a and b else f"{lab} {a or b}"
                                for lab, a, b in o.changes)
        rows.append({
            "Code": o.code(letter) + (" (new)" if o.action == "create" else ""),
            "Action": ACTION_LABEL.get(o.action, o.action),
            "Item": indent + (o.title or ""),
            "Changes": changes,
        })
    return rows


# ── apply ─────────────────────────────────────────────────────────────────────

def apply_plan(plan: Plan, project: dict, me: str | None, notify: bool = False,
               assigner: str = "") -> tuple[bool, list[str]]:
    """Write the plan. Stops at the first failure and says what was done."""
    from core.supabase_client import supabase
    from db import log_status_change, update_row, approve_deliverable_completion, now_iso
    from utils import codes as K

    if not plan.ok:
        return False, ["The plan has errors: nothing was written."]
    pid, letter = project["id"], project.get("code_letter") or ""
    ids: dict = {}
    done: list[str] = []
    created: list[Op] = []

    def db_id(op: Op | None):
        if op is None or op.loose:
            return None
        return op.row["id"] if op.row else ids.get(id(op))

    def write(op: Op, table: str, extra: dict) -> None:
        payload = {**op.fields, **extra}
        if op.action == "create":
            res = supabase.table(table).insert(payload).execute()
            if not res.data:
                raise RuntimeError(f"the database did not return the new {op.kind}")
            ids[id(op)] = res.data[0]["id"]
            created.append(op)
            if op.kind != "deliverable":
                log_status_change(op.kind, ids[id(op)], pid, None, payload.get("status"), me)
        elif payload:
            if op.kind != "deliverable":
                payload["updated_at"] = now_iso()
            old_s = op.row.get("status")
            ok, err, _ = update_row(table, op.row["id"], payload)
            if not ok:
                raise RuntimeError(err)
            new_s = payload.get("status")
            if new_s and new_s != old_s:
                log_status_change(op.kind, op.row["id"], pid, old_s, new_s, me)
        else:
            return
        done.append(f"{ACTION_LABEL.get(op.action, op.action)} {op.kind} {op.code(letter)} — {op.title}")

    try:
        for op in plan.ops:
            if op.kind == "deliverable" and not op.loose:
                write(op, "deliverables", {})
        for op in plan.ops:
            if op.kind == "task":
                extra = {}
                if op.action in ("create", "move"):
                    extra["deliverable_id"] = db_id(op.parent)
                write(op, "tasks", extra)
        for op in plan.ops:
            if op.kind == "subtask":
                extra = {}
                if op.action in ("create", "move"):
                    extra["task_id"] = db_id(op.parent)
                write(op, "subtasks", extra)
        for op in plan.ops:
            if op.kind == "deliverable" and op.complete:
                ok, err = approve_deliverable_completion(db_id(op), me or "", note="Completed by import")
                if not ok:
                    raise RuntimeError(f"sign-off of {op.code(letter)}: {err}")
                done.append(f"✓ signed off {op.code(letter)} — {op.title} (its closed tasks archived)")
    except Exception as exc:
        K.resync_project(pid)
        tail = ("The changes listed above were written; fix the file and import the rest "
                "(items already created now exist: use update/keep for them)." if done
                else "Nothing was written.")
        return False, done + [f"Stopped: {exc}. {tail}"]

    K.resync_project(pid)

    if notify and created:
        try:
            from utils.notifications import send_task_assigned
            pname = project.get("name") or ""
            for op in created:
                if op.kind == "deliverable":
                    continue
                item = {**op.fields, "id": ids.get(id(op)), "sequence_id": op.code(letter),
                        "project_name": pname}
                item.setdefault("priority", "none")
                owner, sup = op.fields.get("owner_email"), op.fields.get("supervisor_email")
                if owner:
                    send_task_assigned(item, owner, assigner)
                if sup and sup != owner:
                    send_task_assigned(item, sup, assigner)
        except Exception as exc:
            done.append(f"(e-mails not sent: {exc})")
    return True, done


# ── guide and prompt ──────────────────────────────────────────────────────────

GUIDE_MD = """
**How the import works**

1. **Prepare the payload.** Copy the prompt below into an LLM (Claude, ChatGPT,
   Gemini…), add at the end what you want to organise — meeting notes, an
   e-mail, a work plan — and ask for the YAML. Or write it by hand.
2. **Paste it above** (YAML or JSON) and press **Validate**. Nothing is written yet.
3. **Read the preview.** Each line shows the code the item will get, the action
   and what changes. Names are matched to the team (*Luigi* → *Luigi Boccia*).
   Any error — an ambiguous name, a ref that does not match its title, an item
   from another project, a duplicate — makes the file invalid: fix it and
   validate again.
4. **Import.** New items are numbered automatically (first free number of
   their parent); a moved task keeps its number when it is free there.

**Actions:** `create`, `update` (only the fields given), `move` (with `from`),
`complete`, `cancel`, `keep` (no change, just to reach the tasks inside).
`description_append` adds to the existing description, `description` replaces it.
Defaults come from `defaults` (supervisor, status, priority); subtasks without
assignee inherit the task's. Nothing is ever deleted: `cancel` sets *Cancelled*.

**Duplicates.** One entry per existing item. Creating an item whose title already
exists under the same parent makes the file invalid (pasting the same file twice
does nothing harmful); tick *Create anyway* only when it is really a new item.
A deliverable can be completed only if, after the import, all its tasks and
subtasks are closed; it is then signed off and its closed work archived.
"""

SCHEMA_YAML = """schema: maic-tasks-import/v1
project: {code: <letter>, name: <acronym or name>}   # must be THIS project
defaults:                         # optional; apply to created items
  supervisor: <name>              # or none
  status: Not started             # Not started | Working on | Blocked | Completed | Cancelled
  priority: medium                # none | low | medium | high | urgent
  subtask_assignee: inherit       # inherit (the task's assignee) or a name
  owner: <name>                   # optional: owner/assignee when not given (default: the importer)
deliverables:
  - action: create|update|complete|cancel|keep
    ref: E.1                      # existing deliverables only (code shown in the app)
    match_title: <current title>  # required for existing items: confirms the ref
    key: <short label>            # optional, unique in the file
    title: <new title>
    type: <deliverable type>
    status: <status>
    owner: <name>
    supervisor: <name>|none
    due: YYYY-MM-DD
    description: <text>           # replaces | description_append: <text> adds
    tasks:
      - action: create|update|move|complete|cancel|keep
        ref: E.1.2                # existing task, under THIS deliverable
        from: E.3.1               # move only: current code of the task to bring here
        match_title: <current title>
        title, priority, status, assignee, supervisor, due, description | description_append
        subtasks:
          - action: create|update|move|complete|cancel|keep   # default create
            ref: E.1.2.1 | from: E.1.3.2
            match_title, title, status, assignee, supervisor, due, description | description_append
  # tasks without a deliverable: a deliverable entry  {action: keep, ref: E.0, tasks: [...]}"""


def build_prompt(project: dict, snap: dict, users: list[dict], type_options: list[str]) -> str:
    """The prompt to paste into an LLM: instructions, schema, valid values,
    team and the current state of this project (refs + titles)."""
    letter = project.get("code_letter") or "?"
    acr, pname = project.get("acronym") or "", project.get("name") or ""
    people = People(users)
    ds = sorted([d for d in snap.get("deliverables", []) if not d.get("is_archived")],
                key=lambda d: d.get("code_no") or 0)
    ts = [t for t in snap.get("tasks", []) if not t.get("is_archived")]
    ss = [s for s in snap.get("subtasks", []) if not s.get("is_archived")]

    def line(code, r, who="owner"):
        bits = [r.get("status") or "Not started", f"{who}: {people.name(r.get('owner_email'))}"]
        if r.get("deadline"):
            bits.append(f"due {str(r['deadline'])[:10]}")
        return f"{code}  \"{r.get('name')}\"  ({', '.join(bits)})"

    def task_block(t, code, ind):
        out = [ind + line(code, t, "assignee")]
        for s in sorted([s for s in ss if s.get("task_id") == t["id"]], key=lambda s: s.get("code_no") or 0):
            out.append(ind + "    " + line(f"{code}.{s.get('code_no')}", s, "assignee"))
        return out

    state = []
    for d in ds:
        dc = f"{letter}.{d.get('code_no')}"
        state.append(line(dc, d) + f"  [type: {d.get('type') or '—'}]")
        for t in sorted([t for t in ts if t.get("deliverable_id") == d["id"]], key=lambda t: t.get("code_no") or 0):
            state += task_block(t, f"{dc}.{t.get('code_no')}", "    ")
    loose = sorted([t for t in ts if not t.get("deliverable_id")], key=lambda t: t.get("code_no") or 0)
    if loose:
        state.append(f"{letter}.0  (tasks without deliverable)")
        for t in loose:
            state += task_block(t, f"{letter}.0.{t.get('code_no')}", "    ")
    team = ", ".join(sorted(u.get("name") or u["email"] for u in users if u.get("email")))

    return f"""You organise the work of a research project into deliverables, tasks and subtasks for the MAIC LAB task manager.
Answer with ONE YAML document that follows the schema below, and nothing else (no comments, no explanations).

RULES
- Everything belongs to project {letter} ({acr} · {pname}): write project: {{code: {letter}, name: {acr or pname}}}.
- Actions: create, update (only the fields you give), move (with from), complete, cancel, keep (no change; use it to reach the tasks inside an existing deliverable).
- Existing items: give ref (their code, e.g. {letter}.1.2) AND match_title (their current title, copied from the state below). Never invent refs.
- New items: action create, no ref — numbers are assigned automatically.
- Do not create an item that already exists: update it or keep it. One entry per existing item.
- A task listed under a deliverable must currently be under it; to bring a task from another deliverable use action: move, from: <its current code>.
- Tasks without a deliverable go in an entry {{action: keep, ref: {letter}.0, tasks: [...]}}.
- description_append adds to the existing description; description replaces it.
- Defaults (supervisor, status, priority) apply to created items; subtasks without assignee inherit the task's assignee.
- Never delete: to drop an item use cancel.
- A deliverable can be completed only if all its tasks and subtasks end up Completed or Cancelled.
- Dates: YYYY-MM-DD. People: use names from the team list (full names are safest).
- Status: Not started | Working on | Blocked | Completed | Cancelled. Priority: none | low | medium | high | urgent.
- Deliverable types: {' | '.join(type_options or ['paper', 'layout', 'prototype'])}.

SCHEMA
{SCHEMA_YAML}

EXAMPLE
schema: maic-tasks-import/v1
project: {{code: {letter}, name: {acr or pname}}}
defaults: {{supervisor: <team member>, status: Not started, priority: medium, subtask_assignee: inherit}}
deliverables:
  - action: create
    title: Demonstrator #2
    type: {(type_options or ['prototype'])[0]}
    owner: <team member>
    due: 2027-03-31
    tasks:
      - title: Layout of the feed network
        assignee: <team member>
        due: 2027-01-15
        subtasks:
          - title: EM simulation of the transition
  - action: keep
    ref: {letter}.1
    match_title: <current title of {letter}.1>
    tasks:
      - action: update
        ref: {letter}.1.2
        match_title: <current title of {letter}.1.2>
        status: Working on
        description_append: Measurements scheduled for next week.

TEAM
{team}

CURRENT STATE OF PROJECT {letter}  (code  "title"  (status, people, due))
{chr(10).join(state) if state else '(empty project)'}

MY REQUEST
<describe here what to add or change, or paste the meeting notes / work plan>
"""
