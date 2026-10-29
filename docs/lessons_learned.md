# Lessons Learned

## 2026-06-10 — Note edits silently lost in task/subtask modals (and paper drafts)

**Symptom.** Some users reported that edits to task and subtask notes were not
saved, even though the app showed "Saved!". Other fields (status, deadline)
saved correctly. Creation modals never lost notes.

**Why we were wrong.** `utils/md_editor.py` renders EasyMDE in an iframe and
mirrors its content into a hidden `st.text_area` ("sink") by dispatching
synthetic `input` events. Streamlit only *commits* a text_area value to the
backend on blur / Ctrl+Enter / **form submit** — and a hidden sink never
receives a blur. Wherever the editor sat inside `st.form` (creation modals,
admin project edit) the form submit committed the pending value and saving
worked; wherever Save was a plain `st.button` (task/subtask edit modals,
paper drafts) the backend read a stale value and silently saved the old notes.

**Rule.** Any `markdown_editor(...)` usage MUST be inside `st.form` with the
save action as `st.form_submit_button`. Never pair the markdown editor with a
plain `st.button` save.

**Bonus rules added in the same fix:**
- Task/subtask updates now send only the fields that actually changed
  (diff vs the snapshot loaded when the modal opened). This prevents two
  users with the same modal open from clobbering each other's notes
  (last-write-wins on the whole row).
- After an `update(...)`, check `res.data`: Supabase/PostgREST returns an
  empty list (no exception) when zero rows are updated, so success messages
  must not be shown unconditionally.

## 2026-10-29 — Body placeholders of the 2026 template carry bullets

**What went wrong.** The per-task slides (layout *Sottotitolo*) were filled
with `_ph_paragraphs` like the per-person pages, and every line — project
name, status, supervisor — rendered with the layout's `▪` bullet and hanging
indent, because the body placeholder inherits a bulleted list style from the
master.

**Rule.** When a template placeholder holds styled lines rather than a list,
call `_ph_paragraphs(..., bullets=False)` (it writes `<a:buNone/>` and zeroes
`marL`/`indent`). Always render a new layout to PNG and look at it before
calling a deck change done.
