"""core/auth.py — Google sign-in.

Two paths, chosen at runtime:

* **Native** (preferred): Streamlit's built-in OIDC auth — ``st.login()`` /
  ``st.user`` — used automatically when an ``[auth]`` section exists in
  secrets.toml. The redirect is issued SERVER-side by Streamlit itself, so it
  works in one tab regardless of how the page is framed. Setup (once):

      # .streamlit/secrets.toml  (and the same in Streamlit Cloud → Secrets)
      [auth]
      redirect_uri = "https://maiclab-tasks.streamlit.app/oauth2callback"
      cookie_secret = "<any long random string>"
      client_id = "<GOOGLE_CLIENT_ID>"
      client_secret = "<GOOGLE_CLIENT_SECRET>"
      server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"

  plus, in Google Cloud Console → Credentials → the OAuth client:
  add  https://maiclab-tasks.streamlit.app/oauth2callback  to the
  *Authorized redirect URIs*. Requires Authlib (in requirements.txt).

* **Legacy** (fallback, active until [auth] is configured): the manual OAuth
  flow with an st.link_button. It opens Google in a SECOND tab and the login
  completes there — a known annoyance, but it works. Both same-tab attempts
  (anchor target=_self, then _top) made Google answer 403, because the app is
  served inside a frame that Google's anti-clickjacking policy rejects and
  that even _top did not escape. Do not retry target tricks here: switch to
  the native path instead, which sidesteps framing entirely.

Authorisation (approved users, roles) stays in OUR users table either way:
Google only proves the identity.
"""

import streamlit as st
import os
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
import json
from core.supabase_client import supabase

# OAuth 2.0 Scopes: basic user info (legacy flow)
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


# ─── Native OIDC path (st.login) ──────────────────────────────────────────────

def _native_auth_available() -> bool:
    """True when Streamlit's built-in auth is usable: recent Streamlit AND an
    [auth] section with a client_id in secrets. Config-driven, so flipping to
    the native flow needs no code change — just the secrets."""
    if not (hasattr(st, "login") and hasattr(st, "user")):
        return False
    try:
        auth_cfg = st.secrets.get("auth", {})
        return bool(auth_cfg.get("client_id")) and bool(auth_cfg.get("cookie_secret"))
    except Exception:
        return False


def _check_login_native() -> bool:
    """st.login()-based flow. Streamlit performs the redirect server-side."""
    if getattr(st.user, "is_logged_in", False):
        # Identity proven by Google; authorisation is still ours to decide.
        if not (st.session_state.get('waiting_approval')
                or st.session_state.get('unauthorized')):
            email = getattr(st.user, "email", None)
            name = getattr(st.user, "name", "") or (email or "").split("@")[0]
            if email:
                process_login(email, name)   # sets flags and reruns
        # fall through to render waiting/unauthorized states below

    st.subheader("MAIC LAB Task Manager")
    st.write("Esegui l'accesso istituzionale per continuare.")

    if st.session_state.get('unauthorized'):
        st.error("⛔ Accesso non autorizzato. Contatta l'amministratore del sistema.")
        if st.button("Riprova / Esci", type="secondary"):
            st.session_state.pop('unauthorized', None)
            try:
                st.logout()
            except Exception:
                st.rerun()
        return False

    if st.session_state.get('waiting_approval'):
        show_waiting_approval()
        return False

    if st.button("🔑 Accedi con Google", type="primary"):
        st.login()
    return False


# ─── Legacy manual OAuth path ─────────────────────────────────────────────────

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
    """Genera il bottone di Login per avviare il flusso OAuth (legacy).

    st.link_button opens Google in a new tab ON PURPOSE: see module docstring —
    same-tab navigation gets 403'ed by Google because of framing.
    """
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
    st.caption(
        "L'accesso si apre in una nuova scheda e continua lì: "
        "puoi chiudere questa dopo il login."
    )


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


def _check_login_legacy() -> bool:
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


# ─── Shared ───────────────────────────────────────────────────────────────────

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
                # Attendance signal for the engagement report. Guarded because
                # process_login can run more than once before `logged_in`
                # short-circuits check_login().
                if not st.session_state.get("_login_recorded"):
                    st.session_state["_login_recorded"] = True
                    try:
                        from db import log_login
                        log_login(email)
                    except Exception:
                        pass    # never let telemetry block a sign-in
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


def check_login():
    """Controlla se l'utente è loggato. Se no, mostra la UI di login."""
    if st.session_state.get('logged_in', False):
        return True

    if _native_auth_available():
        return _check_login_native()
    return _check_login_legacy()


def show_waiting_approval():
    st.warning("⏳ Accesso in attesa di approvazione")
    st.write(f"Gentile {st.session_state.get('user_given_name', str(st.session_state.get('user_email', '')).split('@')[0])}, la tua richiesta di accesso al sistema MAIC LAB è stata registrata.")
    st.write("Un amministratore deve verificare e approvare il tuo account prima che tu possa accedere alle funzionalità del portale.")
    st.info("Riceverai una notifica o potrai riprovare l'accesso più tardi.")
    if st.button("Riprova / Esci", type="secondary"):
        logout()


def logout():
    """Effettua il logout pulendo lo stato (e la sessione nativa, se attiva)."""
    keys_to_clear = ['logged_in', 'user_email', 'user_name', 'user_role', 'waiting_approval', 'user_given_name', 'unauthorized', '_login_recorded']
    for key in keys_to_clear:
        if key in st.session_state:
            del st.session_state[key]
    if _native_auth_available() and getattr(st.user, "is_logged_in", False):
        try:
            st.logout()   # clears the identity cookie and reruns
            return
        except Exception:
            pass
    st.rerun()
