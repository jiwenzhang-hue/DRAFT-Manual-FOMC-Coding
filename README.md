# FOMC manual coding app

A locked-statement coding app with a 65% form / 35% statement layout, Arial font, required presence responses, one horizontally scrolling table of detail questions, and top-three emphasis ranking. General Inflation appears last. Only present indicators require details and ranking.

## 1. Create the Google Sheet

Create a private Google spreadsheet and an empty tab named **Responses**. Copy the spreadsheet ID from its URL: the part between `/d/` and `/edit`.

In Google Cloud Console, select or create a project and enable **Google Sheets API**. Create a service account under **IAM & Admin → Service Accounts**. No project-wide IAM role is needed for this app. Under that account's **Keys → Add key → Create new key**, choose JSON and download the key. Your organization must allow service account keys; if this is disabled, ask your project administrator.

Share the Google spreadsheet with the JSON file's `client_email` as **Editor**. Keep general access Restricted; respondents do not need Sheet access. Do not share the key here or publish it to GitHub.

Reference: https://docs.gspread.org/en/master/oauth2.html

## 2. Upload the app to GitHub

Create a GitHub repository, then upload the contents of this folder (not the enclosing folder):

- draft_form_creation.py
- sheets_storage.py
- response_schema.py
- requirements.txt
- fomc_statements_cleaned.csv
- secrets.example.toml (placeholders only)
- README.md
- .gitignore
- .streamlit/config.toml

The `.streamlit` folder and `.gitignore` are hidden on macOS; press Command+Shift+. in Finder to see them. GitHub's web editor can also create `.streamlit/config.toml` by that exact path.

The bundled CSV contains public FOMC statement text only (`id`, `date`, `text`), with no manual responses. Never upload `.streamlit/secrets.toml`, the service-account JSON key, or a responses CSV.

## 3. Deploy and get the link

Sign in at https://share.streamlit.io using GitHub. Choose **Create app**, select the repository and branch, and use **draft_form_creation.py** as the main file. In Advanced settings select Python 3.11 (or a newer compatible version).

Copy `secrets.example.toml` into the app's **Secrets** settings. Replace the spreadsheet ID and service account placeholders using your downloaded JSON. Keep the actual private-key line breaks inside the triple-quoted string. Do not paste JSON directly into the TOML editor.

Deploy. Streamlit supplies a `.streamlit.app` link. In app sharing settings, choose public viewing if anyone with the link should be able to respond. The response Sheet stays private.

References:
- https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app
- https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management

## 4. Assign a statement and test

The initial assignment matches the local app: `statement_20000202`. Change `ASSIGNED_STATEMENT_ID` near the top of draft_form_creation.py to a unique ID in the CSV. It is deliberately not a URL parameter or responder control. Redeploy after changing the assignment and ask active respondents to reload before beginning.

Open the app link, enter test coder details, complete every presence row, details for any present indicators, and the ranking. Submit. Confirm that a new row appears in **Responses**. The app creates the 122 column headers automatically in an empty tab. Use a fresh empty tab if its schema differs; existing response data is never rewritten.

A submission is successful only when Google Sheets confirms the write. Failed writes leave answers visible and show an error. After success the Submit button is disabled for that browser session. Each row has a UUID `submission_id`; retries check that ID before appending. This is best-effort duplicate protection, not a guarantee across concurrent app instances or new sessions. It does not prevent a respondent from making another submission in a new session.

## Local run

Install requirements and run from this folder:

```
python3 -m pip install -r requirements.txt
python3 -m streamlit run draft_form_creation.py
```

For local Google Sheets writes, place the populated secrets template in `.streamlit/secrets.toml`. The app reads its bundled CSV using a relative path and writes directly to Sheets, not to a local responses CSV.

## Verification status

Layout and conditional form rendering are tested locally with the real CSV. Storage tests use a fake worksheet to check header initialization, RAW append, retry handling, and schema mismatch rejection. A real Google Sheets write and the public deployment still require your Google and GitHub setup.
