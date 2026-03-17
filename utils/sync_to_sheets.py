import gspread
from supabase import create_client, Client
import streamlit as st


def _normalize_rows(data: list[dict]) -> list[list[str]]:
    """Convert a list of dict records to a 2D matrix (header + rows) of strings."""
    if not data:
        return []

    # Keep first-seen order of keys across records.
    columns: list[str] = []
    for row in data:
        for key in row.keys():
            if key not in columns:
                columns.append(key)

    values: list[list[str]] = [columns]
    for row in data:
        values.append(["" if row.get(col) is None else str(row.get(col)) for col in columns])
    return values

def backup_supabase_to_sheets():
    """
    Scarica i dati da Supabase e li sincronizza in un Google Sheet.
    """
    try:
        # 1. Connessione a Supabase (usa le chiavi già presenti nei secrets di Streamlit)
        supabase_url = st.secrets["SUPABASE_URL"]
        supabase_key = st.secrets["SUPABASE_KEY"]
        supabase: Client = create_client(supabase_url, supabase_key)

        # 2. Connessione a Google Sheets tramite gspread
        # Presuppone credenziali service account in st.secrets["gcp_service_account"]
        google_creds = {
            "type": st.secrets["gcp_service_account"]["type"],
            "project_id": st.secrets["gcp_service_account"]["project_id"],
            "private_key_id": st.secrets["gcp_service_account"]["private_key_id"],
            "private_key": st.secrets["gcp_service_account"]["private_key"],
            "client_email": st.secrets["gcp_service_account"]["client_email"],
            "client_id": st.secrets["gcp_service_account"]["client_id"],
            "auth_uri": st.secrets["gcp_service_account"]["auth_uri"],
            "token_uri": st.secrets["gcp_service_account"]["token_uri"],
            "auth_provider_x509_cert_url": st.secrets["gcp_service_account"]["auth_provider_x509_cert_url"],
            "client_x509_cert_url": st.secrets["gcp_service_account"]["client_x509_cert_url"]
        }
        
        gc = gspread.service_account_from_dict(google_creds)
        
        sheet_id = st.secrets.get("GOOGLE_SHEET_BACKUP_ID", "").strip()
        if not sheet_id or sheet_id == "INSERISCI_QUI_IL_TUO_SHEET_ID":
            raise ValueError("GOOGLE_SHEET_BACKUP_ID mancante in .streamlit/secrets.toml")

        spreadsheet = gc.open_by_key(sheet_id)

        # 3. Lista delle tabelle da esportare
        tables_to_sync = [
            "users",
            "projects",
            "deliverables",
            "tasks",
            "subtasks",
            "labels",
            "task_labels",
            "task_dependencies",
            "comments",
            "settings",
        ]

        for table_name in tables_to_sync:
            # Scarica i dati da Supabase
            response = supabase.table(table_name).select("*").execute()
            data = response.data
            
            matrix = _normalize_rows(data)

            # Cerca il foglio (tab) corrispondente o lo crea se non esiste
            try:
                worksheet = spreadsheet.worksheet(table_name)
            except gspread.exceptions.WorksheetNotFound:
                worksheet = spreadsheet.add_worksheet(title=table_name, rows="100", cols="20")

            # Cancella i vecchi dati e incolla quelli nuovi aggiornati.
            worksheet.clear()
            if matrix:
                worksheet.update(matrix)

        return True, "Backup completato con successo su Google Sheets."

    except Exception as e:
        return False, f"Errore durante il backup: {str(e)}"

# Se vuoi testarlo localmente senza Streamlit, puoi usare python utils/sync_to_sheets.py
if __name__ == "__main__":
    success, msg = backup_supabase_to_sheets()
    print(msg)