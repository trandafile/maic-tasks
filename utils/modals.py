import streamlit as st
import datetime
from core.supabase_client import supabase
from utils.md_editor import markdown_editor

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

@st.dialog("Dettaglio Task", width="large")
def task_details_modal(task, can_edit, deliverables=None):
    st.write(f"**ID**: {task.get('sequence_id', f'T-{task.get('id')}')}")
    st.write(f"**Nome**: {task.get('name')}")
    st.markdown("---")
    
    status_map = get_status_color_map()
    
    if can_edit:
        # If deliverables are not provided, try to fetch them to allow moving tasks
        if deliverables is None:
            res = supabase.table("deliverables").select("id, name, project_id").eq("project_id", task.get("project_id")).execute()
            deliverables = res.data or []
            
        # Inline status change
        status_options = list(status_map.keys())
        display_options = list(status_map.values())
        
        curr_status = task.get('status')
        if curr_status not in status_options:
            curr_status = "Not started"
            
        curr_idx = status_options.index(curr_status)
        
        c1, c2, c3 = st.columns(3)
        with c1:
            new_status_display = st.selectbox("Stato del Task", display_options, index=curr_idx)
            new_status = status_options[display_options.index(new_status_display)]
            
        with c2:
            priority_options = ["none", "low", "medium", "high", "urgent"]
            curr_priority = task.get("priority", "medium")
            if curr_priority not in priority_options:
                curr_priority = "medium"
            new_priority = st.selectbox("Priorità", priority_options, index=priority_options.index(curr_priority))
            
        with c3:
            deliv_options = {d["name"]: d["id"] for d in deliverables}
            deliv_options["Nessuno (Generico)"] = None
            
            # Find current deliverable name
            curr_deliv_id = task.get("deliverable_id")
            curr_deliv_name = "Nessuno (Generico)"
            for k, v in deliv_options.items():
                if v == curr_deliv_id:
                    curr_deliv_name = k
                    break
                    
            new_deliv_name = st.selectbox("Deliverable", list(deliv_options.keys()), index=list(deliv_options.keys()).index(curr_deliv_name))
            new_deliv_id = deliv_options[new_deliv_name]

        new_notes = markdown_editor(
            value=task.get("notes") or "",
            key=f"task_notes_{task['id']}",
            height=340,
            label="📝 Note / Descrizione",
        )
            
        st.markdown("---")
        
        c_save, c_empty, c_arch = st.columns([2, 2, 2])
        with c_save:
            if st.button("💾 Salva Modifiche", type="primary", use_container_width=True):
                try:
                    update_data = {
                        "notes": new_notes, 
                        "status": new_status,
                        "priority": new_priority,
                        "deliverable_id": new_deliv_id
                    }
                    
                    # Auto-set completion date if moved to completed just now
                    if new_status == "Completed" and curr_status != "Completed":
                        update_data["completion_date"] = datetime.datetime.now().date().isoformat()
                    # Clear it if moved out of completed
                    elif new_status != "Completed" and curr_status == "Completed":
                        update_data["completion_date"] = None

                    supabase.table("tasks").update(update_data).eq("id", task["id"]).execute()
                    st.success("Salvato!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Errore: {e}")
        with c_arch:
            if st.button("🗑️ Archivia Task", use_container_width=True):
                try:
                    supabase.table("tasks").update({"is_archived": True}).eq("id", task["id"]).execute()
                    st.rerun()
                except Exception as e:
                    st.error(f"Errore: {e}")
    else:
        st.write(f"**Stato**: {status_map.get(task.get('status', 'Not started'))}")
        st.write(f"**Priorità**: {render_priority_badge(task.get('priority'))}")
        if task.get("completion_date"):
            st.write(f"**Completato il**: {task.get('completion_date')}")
        st.write("**Note/Descrizione**:")
        st.markdown(task.get("notes") or "*Nessuna nota fornita.*")


@st.dialog("Dettaglio Subtask", width="large")
def subtask_details_modal(subtask, can_edit):
    st.write(f"**Nome**: {subtask.get('name')}")
    st.markdown("---")
    
    status_map = get_status_color_map()
    
    if can_edit:
        status_options = list(status_map.keys())
        display_options = list(status_map.values())
        
        curr_status = subtask.get('status')
        if curr_status not in status_options:
            curr_status = "Not started"
            
        new_status_display = st.selectbox("Stato del Subtask", display_options, index=status_options.index(curr_status))
        new_status = status_options[display_options.index(new_status_display)]
        
        new_notes = markdown_editor(
            value=subtask.get("notes") or "",
            key=f"subtask_notes_{subtask['id']}",
            height=300,
            label="📝 Note / Descrizione",
        )
            
        st.markdown("---")
        
        c_save, c_empty, c_arch = st.columns([2, 2, 2])
        with c_save:
            if st.button("💾 Salva Modifiche", key="save_st", type="primary", use_container_width=True):
                try:
                    supabase.table("subtasks").update({"notes": new_notes, "status": new_status}).eq("id", subtask["id"]).execute()
                    st.success("Salvato!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Errore: {e}")
        with c_arch:
            if st.button("🗑️ Archivia Subtask", key="arch_st", use_container_width=True):
                try:
                    supabase.table("subtasks").update({"is_archived": True}).eq("id", subtask["id"]).execute()
                    st.rerun()
                except Exception as e:
                    st.error(f"Errore: {e}")
    else:
        st.write(f"**Stato**: {status_map.get(subtask.get('status', 'Not started'))}")
        st.write("**Note/Descrizione**:")
        st.markdown(subtask.get("notes") or "*Nessuna nota fornita.*")
