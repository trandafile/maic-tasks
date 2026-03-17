import streamlit as st
import os
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
import json
from core.supabase_client import supabase

# OAuth 2.0 Scopes: basic user info
SCOPES = [
    'openid',
    'https://www.googleapis.com/auth/userinfo.email',
    'https://www.googleapis.com/auth/userinfo.profile',
]

def get_secret(key, default=None):
    """Accede in modo sicuro a st.secrets o env per evitare FileNotFoundError"""
    val = os.environ.get(key)
    if val is not None:
        return val
        
    try:
        return st.secrets[key]
    except (KeyError, FileNotFoundError, Exception):
        pass
    
    return default

def init_oauth_flow():
    """Inizializza il flusso OAuth 2.0 usando st.secrets"""
    client_id = get_secret("GOOGLE_CLIENT_ID")
    client_secret = get_secret("GOOGLE_CLIENT_SECRET")
    redirect_uri_val = get_secret("GOOGLE_REDIRECT_URI", "http://localhost:8501")
    
    if not client_id or not client_secret:
        return None

    client_config = {
        "web": {
            "client_id": client_id,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_secret": client_secret,
            "redirect_uris": [redirect_uri_val, "http://localhost:8501"],
        }
    }

    flow = Flow.from_client_config(
        client_config,
        scopes=SCOPES,
        redirect_uri=redirect_uri_val
    )
    return flow

def login_button():
    """Genera il bottone di Login per avviare il flusso OAuth."""
    import urllib.parse

    client_id = get_secret("GOOGLE_CLIENT_ID")
    redirect_uri = get_secret("GOOGLE_REDIRECT_URI", "http://localhost:8501")

    if not client_id:
        st.warning("⚠️ In attesa delle credenziali Google OAuth (GOOGLE_CLIENT_ID in secrets.toml).")
        # Fallback to mock form for development continuity until secrets are filled
        mock_email = st.text_input("Mock Login (Dev)", placeholder="luigi.boccia@unical.it")
        if st.button("Simula Login (MOCK)", type="primary"):
            process_login(mock_email, "Dev User")
        return

    params = {
        'client_id': client_id,
        'redirect_uri': redirect_uri,
        'response_type': 'code',
        'scope': 'openid email profile',
        'prompt': 'consent',
        'access_type': 'online',
    }
    auth_url = 'https://accounts.google.com/o/oauth2/auth?' + urllib.parse.urlencode(params)

    st.link_button("🔑 Accedi con Google", auth_url, use_container_width=False, type="primary")

def process_login(email: str, name: str):
    """Verifica e processa l'utente a livello Supabase dopo il login Google."""
    try:
        # Check if user exists
        response = supabase.table("users").select("*").eq("email", email).execute()
        users = response.data
        
        if users and len(users) > 0:
            user = users[0]
            if user.get("is_approved"):
                st.session_state.logged_in = True
                st.session_state.user_email = email
                st.session_state.user_name = name or user.get("name")
                st.session_state.user_role = user.get("role")
                st.session_state.waiting_approval = False
                st.rerun()
            else:
                st.session_state.waiting_approval = True
                st.session_state.user_given_name = name
                st.session_state.user_email = email
                st.rerun()
        else:
            # User not pre-approved by admin → access denied, no auto-registration
            st.session_state.unauthorized = True
            st.session_state.user_given_name = name
            st.rerun()
            
    except Exception as e:
        st.error(f"Errore durante l'accesso al database: {e}")

def handle_oauth_callback():
    """Gestisce il ritorno da Google con il codice di autorizzazione nell'URL."""
    if 'code' in st.query_params:
        code = st.query_params['code']
        # Remove code from URL
        del st.query_params['code']
        
        flow = init_oauth_flow()
        if not flow: return
        
        try:
            flow.fetch_token(code=code)
            creds = flow.credentials
            
            user_info_service = build('oauth2', 'v2', credentials=creds)
            user_info = user_info_service.userinfo().get().execute()
            
            email = user_info.get('email')
            name = f"{user_info.get('given_name', '')} {user_info.get('family_name', '')}".strip()
            
            process_login(email, name)
             
        except Exception as e:
             st.error(f"Errore durante l'autenticazione OAuth: {e}")

def check_login():
    """Controlla se l'utente è loggato. Se no, mostra la UI di login."""
    if st.session_state.get('logged_in', False):
        return True
        
    st.subheader("MAIC LAB Task Manager")
    st.write("Esegui l'accesso istituzionale per continuare.")
    
    handle_oauth_callback()

    if st.session_state.get('unauthorized'):
        st.error("⛔ Accesso non autorizzato. Contatta l'amministratore del sistema.")
        if st.button("Riprova / Esci", type="secondary"):
            st.session_state.pop('unauthorized', None)
            st.rerun()
        return False

    if st.session_state.get('waiting_approval'):
         show_waiting_approval()
         return False

    login_button()
    return False

def show_waiting_approval():
    st.warning("⏳ Accesso in attesa di approvazione")
    st.write(f"Gentile {st.session_state.get('user_given_name', str(st.session_state.get('user_email', '')).split('@')[0])}, la tua richiesta di accesso al sistema MAIC LAB è stata registrata.")
    st.write("Un amministratore deve verificare e approvare il tuo account prima che tu possa accedere alle funzionalità del portale.")
    st.info("Riceverai una notifica o potrai riprovare l'accesso più tardi.")
    if st.button("Riprova / Esci", type="secondary"):
        logout()

def logout():
    """Effettua il logout pulendo lo stato."""
    keys_to_clear = ['logged_in', 'user_email', 'user_name', 'user_role', 'waiting_approval', 'user_given_name', 'unauthorized']
    for key in keys_to_clear:
        if key in st.session_state:
            del st.session_state[key]
    st.rerun()
