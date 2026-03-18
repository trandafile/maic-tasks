import datetime as _dt
import streamlit as st

from core.master_status_report import build_master_status_report_markdown
from utils.notifications import send_master_status_report_to_admins


def show_master_status_report():
    if st.session_state.get("user_role") != "admin":
        st.error("Admins only.")
        return

    st.title("Master Status Report")
    st.caption("Executive, full-hierarchy snapshot (Projects → Deliverables → Tasks → Subtasks).")

    col_a, col_b, col_c = st.columns([1.2, 1.2, 6])
    with col_a:
        show_archived = st.checkbox("Include archived", value=False, key="msr_arch")
    with col_b:
        auto_generate = st.checkbox("Auto-generate", value=True, key="msr_auto")

    payload = None
    if auto_generate or st.button("Generate report", type="primary", key="msr_gen"):
        try:
            payload = build_master_status_report_markdown(show_archived=show_archived)
        except Exception as e:
            st.error(f"Report generation error: {e}")
            return

    if not payload:
        st.info("Generate the report to view/export it.")
        return

    md_text = payload.markdown

    # Download
    st.download_button(
        label="⬇️ Download Markdown",
        data=md_text,
        file_name="maic_lab_status.md",
        mime="text/markdown",
        key="msr_dl_md",
        use_container_width=False,
    )

    # Email send
    if st.button("✉️ Email to all admins", type="secondary", key="msr_email"):
        subject = f"[MAIC LAB] Master Status Report — {_dt.date.today().isoformat()}"
        ok, sent, total = send_master_status_report_to_admins(subject=subject, body=md_text)
        if ok:
            st.success(f"Sent to {sent}/{total} admins.")
        else:
            st.warning(f"Sent to {sent}/{total} admins (some failures). Check server logs.")

    st.divider()

    # Render per project
    for proj_name, block in payload.by_project:
        with st.expander(proj_name, expanded=False):
            st.markdown(block)

