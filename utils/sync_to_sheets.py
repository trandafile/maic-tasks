import gspread
from gspread.exceptions import SpreadsheetNotFound, APIError
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
        gcp_sa = st.secrets["gcp_service_account"]
        required = [
            "type", "project_id", "private_key_id", "private_key",
            "client_email", "client_id", "auth_uri", "token_uri",
            "auth_provider_x509_cert_url", "client_x509_cert_url",
        ]
        missing = [k for k in required if not gcp_sa.get(k)]
        if missing:
            raise ValueError(f"Chiavi mancanti in gcp_service_account: {', '.join(missing)}")

        google_creds = {k: gcp_sa[k] for k in required}

        try:
            gc = gspread.service_account_from_dict(google_creds)
        except Exception as e:
            return False, (
                f"Errore autenticazione service account ({type(e).__name__}): {e}. "
                "Controlla private_key e formato sezione [gcp_service_account]."
            )
        
        sheet_id = st.secrets.get("GOOGLE_SHEET_BACKUP_ID", "").strip()
        if not sheet_id or sheet_id == "INSERISCI_QUI_IL_TUO_SHEET_ID":
            raise ValueError("GOOGLE_SHEET_BACKUP_ID mancante in .streamlit/secrets.toml")

        try:
            spreadsheet = gc.open_by_key(sheet_id)
        except SpreadsheetNotFound as e:
            sa_email = google_creds.get("client_email", "service account")
            return False, (
                f"Google Sheet non trovato o non condiviso ({type(e).__name__}). "
                f"Condividi il file con: {sa_email} (permesso Editor)."
            )
        except APIError as e:
            return False, (
                f"Errore API Google ({type(e).__name__}): {e}. "
                "Verifica che Google Sheets API e Google Drive API siano abilitate nel progetto GCP."
            )
        except Exception as e:
            return False, f"Errore apertura Google Sheet ({type(e).__name__}): {e}"

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

        synced = []
        for table_name in tables_to_sync:
            # Scarica i dati da Supabase
            try:
                response = supabase.table(table_name).select("*").execute()
                data = response.data
            except Exception as e:
                return False, f"Errore lettura tabella '{table_name}' da Supabase ({type(e).__name__}): {e}"
            
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
            synced.append(f"{table_name} ({max(len(matrix)-1, 0)} righe)")

        return True, "Backup completato con successo: " + ", ".join(synced)

    except Exception as e:
        return False, f"Errore durante il backup ({type(e).__name__}): {e}"

# Se vuoi testarlo localmente senza Streamlit, puoi usare python utils/sync_to_sheets.py
if __name__ == "__main__":
    success, msg = backup_supabase_to_sheets()
    print(msg)