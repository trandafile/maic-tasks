import gspread
from gspread.exceptions import SpreadsheetNotFound, APIError
from supabase import create_client, Client
import streamlit as st


def _normalize_rows(data: list[dict]) -> list[list[str]]:
    """Convert a list of dict records to a 2D matrix (header + rows) of strings."""
    if not data:
        return []

    columns: list[str] = []
    for row in data:
        for key in row.keys():
            if key not in columns:
                columns.append(key)

    values: list[list[str]] = [columns]
    for row in data:
        values.append([
            "" if row.get(col) is None else str(row.get(col))
            for col in columns
        ])
    return values


def backup_supabase_to_sheets():
    """
    Scarica i dati da Supabase e li sincronizza in un Google Sheet.
    """
    try:
        # 1. Connessione a Supabase con la secret key (bypassa RLS)
        supabase_url = st.secrets["SUPABASE_URL"]
        supabase_key = st.secrets["SUPABASE_SECRET_KEY"]
        supabase: Client = create_client(supabase_url, supabase_key)

        # 2. Connessione a Google Sheets tramite service account
        gcp_sa = st.secrets["gcp_service_account"]
        required = [
            "type", "project_id", "private_key_id", "private_key",
            "client_email", "client_id", "auth_uri", "token_uri",
            "auth_provider_x509_cert_url", "client_x509_cert_url",
        ]
        missing = [k for k in required if not gcp_sa.get(k)]
        if missing:
            raise ValueError(
                f"Chiavi mancanti in gcp_service_account: {', '.join(missing)}"
            )

        google_creds = {k: gcp_sa[k] for k in required}

        try:
            gc = gspread.service_account_from_dict(google_creds)
        except Exception as e:
            return False, (
                f"Errore autenticazione service account ({type(e).__name__}): {e}. "
                "Controlla private_key e formato sezione [gcp_service_account]."
            )

        sheet_id = st.secrets.get("GOOGLE_SHEET_BACKUP_ID", "").strip()
        if not sheet_id:
            raise ValueError(
                "GOOGLE_SHEET_BACKUP_ID mancante in .streamlit/secrets.toml"
            )

        try:
            spreadsheet = gc.open_by_key(sheet_id)
        except SpreadsheetNotFound:
            sa_email = google_creds.get("client_email", "service account")
            return False, (
                f"Google Sheet non trovato o non condiviso. "
                f"Condividi il file con: {sa_email} (permesso Editor)."
            )
        except APIError as e:
            return False, (
                f"Errore API Google ({type(e).__name__}): {e}. "
                "Verifica che Google Sheets API e Google Drive API siano "
                "abilitate nel progetto GCP."
            )
        except Exception as e:
            return False, f"Errore apertura Google Sheet ({type(e).__name__}): {e}"

        # 3. Tabelle da esportare
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

            # Leggi da Supabase
            try:
                response = supabase.table(table_name).select("*").execute()
                data = response.data
            except Exception as e:
                return False, (
                    f"Errore lettura tabella '{table_name}' "
                    f"({type(e).__name__}): {e}"
                )

            matrix = _normalize_rows(data)
            row_count = max(len(matrix) - 1, 0)

            # Trova o crea il foglio corrispondente
            try:
                worksheet = spreadsheet.worksheet(table_name)
            except gspread.exceptions.WorksheetNotFound:
                worksheet = spreadsheet.add_worksheet(
                    title=table_name,
                    rows=str(max(row_count + 20, 100)),
                    cols="30",
                )

            # Sovrascrivi con i dati aggiornati
            worksheet.clear()
            if matrix:
                worksheet.update(range_name="A1", values=matrix)

            synced.append(f"{table_name} ({row_count} righe)")

        return True, "Backup completato: " + ", ".join(synced)

    except Exception as e:
        return False, f"Errore durante il backup ({type(e).__name__}): {e}"


if __name__ == "__main__":
    success, msg = backup_supabase_to_sheets()
    print(msg)