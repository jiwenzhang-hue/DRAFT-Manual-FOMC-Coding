"""Server-side Google Sheets persistence. No credentials are stored in source."""
import threading

import streamlit as st

from response_schema import HEADERS


@st.cache_resource
def write_lock():
    return threading.Lock()


def append_to_worksheet(worksheet, response):
    missing = set(HEADERS) - set(response)
    if missing:
        raise ValueError("Submission is missing required output columns.")
    current_headers = worksheet.row_values(1)
    if not current_headers:
        if worksheet.get_all_values():
            raise ValueError("Use an empty worksheet with no existing data.")
        if worksheet.col_count < len(HEADERS):
            worksheet.resize(cols=len(HEADERS))
        worksheet.update(range_name="A1", values=[HEADERS], value_input_option="RAW")
    elif current_headers != HEADERS:
        raise ValueError("Response worksheet headers differ. Use a new empty worksheet; do not overwrite existing responses.")

    # Best-effort retry protection for a previously confirmed server-side append.
    # The ID also makes ambiguous retries easy to identify in the Sheet.
    submission_id = response["submission_id"]
    if not submission_id:
        raise ValueError("A submission ID is required.")
    if submission_id in worksheet.col_values(1)[1:]:
        return
    worksheet.append_row(
        [response[column] for column in HEADERS],
        value_input_option="RAW",
        insert_data_option="INSERT_ROWS",
        table_range="A1",
    )


def append_response(response):
    import gspread
    from google.oauth2.service_account import Credentials

    settings = st.secrets["google_sheets"]
    credentials = Credentials.from_service_account_info(
        dict(st.secrets["gcp_service_account"]),
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    client = gspread.authorize(credentials)
    spreadsheet = client.open_by_key(settings["spreadsheet_id"])
    worksheet = spreadsheet.worksheet(settings.get("worksheet", "Responses"))
    with write_lock():
        append_to_worksheet(worksheet, response)
