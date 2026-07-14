"""core/supabase_client.py — the shared Supabase client.

Credentials are looked up in this order:

1. environment variables ``SUPABASE_URL`` / ``SUPABASE_KEY`` — used by the
   GitHub Actions cron, which has no Streamlit runtime;
2. ``st.secrets`` — used by the app locally and on Streamlit Cloud.

Streamlit is imported lazily, so headless scripts (scripts/*.py) can import
this module without Streamlit installed or running.
"""

import os

from supabase import create_client, Client


def _from_streamlit_secrets() -> tuple[str | None, str | None]:
    """Read the secrets, tolerating every way this can fail off-Streamlit.

    Touching st.secrets without a secrets.toml raises (and it is *not* a
    KeyError), so the whole lookup is guarded rather than the key access.
    """
    try:
        import streamlit as st
        return st.secrets.get("SUPABASE_URL"), st.secrets.get("SUPABASE_KEY")
    except Exception:
        return None, None


def get_supabase_client() -> Client:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")

    if not (url and key):
        s_url, s_key = _from_streamlit_secrets()
        url = url or s_url
        key = key or s_key

    if not url or not key:
        msg = (
            "Supabase credentials not found. Set SUPABASE_URL and SUPABASE_KEY "
            "in .streamlit/secrets.toml, or as environment variables."
        )
        try:
            import streamlit as st
            st.error(msg)
            st.stop()
        except Exception:
            pass
        raise RuntimeError(msg)

    return create_client(url, key)


supabase = get_supabase_client()
