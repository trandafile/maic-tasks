import os
from supabase import create_client, Client
import streamlit as st

def get_supabase_client() -> Client:
    """
    Initializes and returns a Supabase client using credentials from Streamlit secrets.
    """
    try:
        # Check if running in Streamlit cloud or locally with secrets
        url: str = st.secrets["SUPABASE_URL"]
        key: str = st.secrets["SUPABASE_KEY"]
    except KeyError:
        # Fallback to environment variables if not in st.secrets
        url: str = os.environ.get("SUPABASE_URL")
        key: str = os.environ.get("SUPABASE_KEY")

        if not url or not key:
            st.error("Supabase credentials not found. Please setup .streamlit/secrets.toml with SUPABASE_URL and SUPABASE_KEY.")
            st.stop()
            
    return create_client(url, key)

supabase = get_supabase_client()
