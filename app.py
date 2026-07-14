import streamlit as st
import os
import sys
from pathlib import Path

# ── MAIC LAB branding ─────────────────────────────────────────────────────────
# Drop a logo file into  assets/  to brand the whole app. The first existing of
# these names is used; PNG/SVG with transparent background works best.
_ASSETS_DIR = Path(__file__).resolve().parent / "assets"
_LOGO_CANDIDATES = [
    "maic_logo.png", "maic_logo.svg", "maic_logo.jpg", "maic_logo.jpeg",
    "logo.png", "logo.svg",
]
# A separate small square mark for the collapsed sidebar / browser tab (optional).
_ICON_CANDIDATES = ["maic_icon.png", "maic_mark.png", "maic_logo.png", "logo.png"]


def _first_existing(names) -> str | None:
    for n in names:
        p = _ASSETS_DIR / n
        if p.exists():
            return str(p)
    return None


_LOGO_PATH = _first_existing(_LOGO_CANDIDATES)
_ICON_PATH = _first_existing(_ICON_CANDIDATES)

# Configure main page BEFORE any other Streamlit calls
st.set_page_config(
    page_title="MAIC LAB - Task Manager",
    page_icon=_ICON_PATH or "✅",
    layout="wide",
)


def _apply_branding():
    """Show the MAIC LAB logo across the app (top bar + sidebar). Falls back to
    a text wordmark if no logo file has been added to assets/."""
    if _LOGO_PATH and hasattr(st, "logo"):
        try:
            st.logo(_LOGO_PATH, icon_image=_ICON_PATH or _LOGO_PATH, size="large")
            return
        except Exception:
            pass  # older Streamlit / bad file → fall through to text wordmark
    with st.sidebar:
        st.markdown(
            "<div style='font-weight:800;font-size:1.1rem;color:#1A3E8B;"
            "letter-spacing:0.02em;margin-bottom:6px'>MAIC&nbsp;LAB</div>",
            unsafe_allow_html=True,
        )

# Custom CSS for UI enhancements (matching hipa)
st.markdown("""
    <style>
    @keyframes blink {
        0% { opacity: 1; }
        50% { opacity: 0.2; }
        100% { opacity: 1; }
    }
    .blink-icon {
        animation: blink 1.2s infinite;
        font-size: 1.3rem;
        vertical-align: middle;
    }
    /* Global markdown note typography: compact heading hierarchy */
    div[data-testid="stMarkdownContainer"] h1 {
        font-size: 1.08rem;
        font-weight: 700;
        line-height: 1.35;
        margin: 0.65rem 0 0 0;
    }
    div[data-testid="stMarkdownContainer"] h2 {
        font-size: 1rem;
        font-weight: 700;
        line-height: 1.35;
        margin: 0.6rem 0 0 0;
    }
    div[data-testid="stMarkdownContainer"] h3 {
        font-size: 1rem;
        font-weight: 500;
        line-height: 1.35;
        text-decoration: underline;
        text-underline-offset: 2px;
        margin: 0.55rem 0 0 0;
    }
    div[data-testid="stMarkdownContainer"] h1 + p,
    div[data-testid="stMarkdownContainer"] h2 + p,
    div[data-testid="stMarkdownContainer"] h3 + p {
        margin-top: 0 !important;
    }
    div[data-testid="stMarkdownContainer"] p,
    div[data-testid="stMarkdownContainer"] li {
        line-height: 1.5;
        margin-bottom: 0.35rem;
    }
    div[data-testid='stHorizontalBlock'] { 
        border-bottom: 1px solid #f0f0f0; 
        padding-top: 10px; 
        padding-bottom: 10px; 
        border-radius: 4px; 
    } 
    div[data-testid='stHorizontalBlock']:nth-of-type(even) { 
        background-color: #f9f9f0; 
    } 
    div[data-testid='stHorizontalBlock']:nth-of-type(odd) { 
        background-color: #ffffff; 
    } 
    div[data-testid='stHorizontalBlock']:first-of-type {
        background-color: #eeeeee;
        font-weight: bold;
    }

    /* ── Task / subtask hierarchy rows ─────────────────────────────────────
       The row renderers emit a marker div (.maic-task-row / .maic-subtask-row)
       inside their column, so we can tint the whole row band and give subtasks
       a lighter shade than their parent task. These rules come AFTER the
       nth-of-type striping above so they win for hierarchy rows only.        */

    /* Nested column blocks (e.g. the action buttons) must not repaint the band */
    div[data-testid='stHorizontalBlock'] div[data-testid='stHorizontalBlock'] {
        background-color: transparent !important;
    }
    div[data-testid='stHorizontalBlock']:has(.maic-task-row) {
        background-color: #E9ECEF !important;
    }
    div[data-testid='stHorizontalBlock']:has(.maic-subtask-row) {
        background-color: #F7F8FA !important;
    }
    </style>
""", unsafe_allow_html=True)

# Add current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core.auth import check_login, logout

def _load_build_label(default: str = "beta 1.18.72") -> str:
    """Load build label from the same file used by upload.bat."""
    version_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".upload_version.txt")
    try:
        with open(version_file, "r", encoding="utf-8") as f:
            value = f.readline().strip()
            return value if value else default
    except OSError:
        return default


APP_BUILD_LABEL = _load_build_label()

def init_session_state():
    """Inizializza tutte le chiavi necessarie nello stato della sessione"""
    keys_default = {
        'logged_in': False,
        'user_email': None,
        'user_name': None,
        'user_role': None,
        'user_given_name': None,
        'waiting_approval': False,
        'current_page': 'Dashboard',
        '_scheduler_done': False,
    }
    for k, v in keys_default.items():
        if k not in st.session_state:
            st.session_state[k] = v

# Import views
from views.dashboard import show_dashboard
from views.projects import show_projects
from views.deliverables import show_deliverables
from views.calendar import show_calendar
from views.reports import show_reports
from views.admin import show_admin
from views.master_status_report import show_master_status_report
from views.my_papers import show_my_papers
from views.my_paper_drafts import show_my_paper_drafts
from views.conferences import show_conference_calendar
from views.conference_papers import show_conference_papers
from views.timesheets import show_timesheets
from views.contracts import show_contracts
from views.people import show_people

def _run_scheduler_once():
    """Run deadline check once per session (avoid repeated calls on rerender)."""
    if st.session_state.get("_scheduler_done"):
        return
    st.session_state["_scheduler_done"] = True
    try:
        from utils.scheduler import check_and_send_deadline_reminders
        check_and_send_deadline_reminders()
    except Exception as e:
        print(f"[app] Errore scheduler: {e}")


def main():
    init_session_state()

    # MAIC LAB logo on every page (login screen included)
    _apply_branding()

    # Se non siamo loggati, mostra pagina login auth di Google
    is_authenticated = check_login()
    if not is_authenticated:
        return

    # Run daily deadline check (once per session after login)
    _run_scheduler_once()

    # Costruzione della Sidebar
    with st.sidebar:
        st.markdown(f"**User:** {st.session_state.get('user_name', '')}")
        st.markdown(f"**Role:** {str(st.session_state.get('user_role', '')).capitalize()}")
        st.markdown("---")

        # Main workspace pages
        pages = ["Dashboard", "Projects", "Deliverables", "Calendar", "Reports", "Time Sheets"]

        # Paper-related pages, grouped under a "Papers" heading
        paper_pages = ["My Papers", "My Paper Drafts", "Conference Calendar", "Conference Paper Drafts"]

        # Admin-only pages
        admin_pages = []
        if st.session_state.get('user_role') == 'admin':
            admin_pages = ["People", "Contracts", "Admin Panel", "Master Status Report"]

        current = st.session_state.get('current_page', 'Dashboard')

        def _nav_button(p: str):
            if st.button(p, key=f"nav_{p}", use_container_width=True,
                         type="primary" if current == p else "secondary"):
                st.session_state['current_page'] = p
                st.rerun()

        # Render main pages
        for p in pages:
            _nav_button(p)

        # Papers block
        st.markdown(
            "<div style='font-size:0.7rem;font-weight:700;letter-spacing:0.08em;"
            "color:#888;text-transform:uppercase;margin:10px 0 2px 4px'>📄 Papers</div>",
            unsafe_allow_html=True,
        )
        for p in paper_pages:
            _nav_button(p)

        # Admin block
        if admin_pages:
            st.markdown(
                "<div style='font-size:0.7rem;font-weight:700;letter-spacing:0.08em;"
                "color:#888;text-transform:uppercase;margin:10px 0 2px 4px'>🛠️ Admin</div>",
                unsafe_allow_html=True,
            )
            for p in admin_pages:
                _nav_button(p)

        st.markdown("---")
        if st.button("Logout", use_container_width=True):
            logout()

        st.markdown("---")
        st.caption(f"Build: {APP_BUILD_LABEL}")

    # Content Switcher
    page = st.session_state.get('current_page', 'Dashboard')
    
    if page == "Dashboard":
        show_dashboard()
    elif page in ("Projects", "Active Tasks"):  # old label kept for stale sessions
        show_projects()
    elif page == "Deliverables":
        show_deliverables()
    elif page == "Calendar":
        show_calendar()
    elif page == "Reports":
        show_reports()
    elif page == "My Papers":
        show_my_papers()
    elif page == "My Paper Drafts":
        show_my_paper_drafts()
    elif page == "Conference Calendar":
        show_conference_calendar()
    elif page == "Conference Paper Drafts":
        show_conference_papers()
    elif page == "Time Sheets":
        show_timesheets()
    elif page == "Contracts":
        show_contracts()
    elif page == "People":
        show_people()
    elif page == "Admin Panel":
        show_admin()
    elif page == "Master Status Report":
        show_master_status_report()

if __name__ == "__main__":
    main()
