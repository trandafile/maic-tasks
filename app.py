import streamlit as st
import os
import sys

# Configure main page BEFORE any other Streamlit calls
st.set_page_config(
    page_title="MAIC LAB - Task Manager", 
    page_icon="✅", 
    layout="wide"
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
    </style>
""", unsafe_allow_html=True)

# Add current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core.auth import check_login, logout

def init_session_state():
    """Inizializza tutte le chiavi necessarie nello stato della sessione"""
    keys_default = {
        'logged_in': False,
        'user_email': None,
        'user_name': None,
        'user_role': None,
        'user_given_name': None,
        'waiting_approval': False,
        'current_page': 'Dashboard'
    }
    for k, v in keys_default.items():
        if k not in st.session_state:
            st.session_state[k] = v

# Import views
from views.dashboard import show_dashboard
from views.projects import show_projects
from views.reports import show_reports

def dummy_page_calendar():
    st.title("Calendar")
    st.write("This is the Calendar view. (To be implemented)")

def dummy_page_admin():
    st.title("Admin Panel")
    st.write("This is the Admin Panel. (To be implemented)")
    st.warning("Area riservata agli amministratori per gestione utenti, labels e progetti globali.")

def main():
    init_session_state()

    # Se non siamo loggati, mostra pagina login auth di Google
    is_authenticated = check_login()
    if not is_authenticated:
        return

    # Costruzione della Sidebar
    with st.sidebar:
        st.markdown(f"**Utente:** {st.session_state.get('user_name', '')}")
        st.markdown(f"**Ruolo:** {str(st.session_state.get('user_role', '')).capitalize()}")
        st.markdown("---")
        
        # Base pages for user
        pages = ["Dashboard", "Projects", "Calendar", "Reports"]
        
        # Pannello Admin solo per admin
        if st.session_state.get('user_role') == 'admin':
            pages.append("Admin Panel")
            
        st.markdown("**Navigazione**")
        current = st.session_state.get('current_page', 'Dashboard')
        
        # Render stylized navigation buttons
        for p in pages:
            if st.button(p, key=f"nav_{p}", use_container_width=True, type="primary" if current == p else "secondary"):
                st.session_state['current_page'] = p
                st.rerun()
        
        st.markdown("---")
        if st.button("Logout", use_container_width=True):
            logout()

    # Content Switcher
    page = st.session_state.get('current_page', 'Dashboard')
    
    if page == "Dashboard":
        show_dashboard()
    elif page == "Projects":
        show_projects()
    elif page == "Calendar":
        dummy_page_calendar()
    elif page == "Reports":
        show_reports()
    elif page == "Admin Panel":
        dummy_page_admin()

if __name__ == "__main__":
    main()
