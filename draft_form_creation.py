from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import re
import uuid
from zipfile import BadZipFile

import pandas as pd
import streamlit as st

from cloud_storage import (
    save_cloud_response,
    owner_download_panel,
    StorageError,
)


# ============================================================
# SETTINGS
# ============================================================

APP_FOLDER = Path(__file__).resolve().parent

RAW_EXCEL = APP_FOLDER / "FOMC_10_Selected_Statements.xlsx"
STATEMENTS_SHEET = "All 10 statements"

FORM_VERSION = 3

SELECTED_IDS = [
    "statement_20060629",
    "statement_20110809",
    "statement_20171101",
    "statement_20190130",
    "statement_20200916",
    "statement_20221214",
    "statement_20250129",
    "statement_20120913",
    "statement_20150617",
    "statement_20230614",
]


# ============================================================
# INDICATORS
# ============================================================

INDICATOR_DESCRIPTIONS = {
    "Core Inflation": (
        "Core or underlying inflation without specifying CPI or PCE."
    ),
    "Core CPI": (
        "Consumer Price Index (CPI) inflation excluding food and energy."
    ),
    "Core PCE": (
        "Personal Consumption Expenditures (PCE) inflation excluding "
        "food and energy; also includes trimmed-mean PCE."
    ),
    "Headline Inflation": (
        "Overall or headline inflation without specifying CPI or PCE."
    ),
    "Headline CPI": (
        "Overall CPI inflation, including food and energy."
    ),
    "Headline PCE": (
        "Overall PCE inflation, including food and energy."
    ),
    "Services": "Service prices or services inflation.",
    "Goods": "Goods prices, including consumer and imported goods.",
    "Housing": (
        "House prices, rents, shelter costs, or housing services prices."
    ),
    "Energy": "Energy prices, including oil, gasoline, and utilities.",
    "Food": (
        "Food prices or food inflation, beyond references to exclusions."
    ),
    "PPI": "Producer Price Index (PPI): prices received by producers.",
    "Wage Inflation": (
        "Wage growth or labor compensation, including earnings "
        "and employment costs."
    ),
    "Inflation Expectations": (
        "Expected future inflation, including surveys "
        "and market-based measures."
    ),
    "Commodity Prices": (
        "Commodity or raw-material prices, including crude oil."
    ),
    "General Inflation": (
        "Inflation or price discussion without a specific price, "
        "sector, or measure."
    ),
}

INDICATORS = list(INDICATOR_DESCRIPTIONS)

EMPHASIS_OPTIONS = ["Low", "High"]

OPTIONS = {
    "Level": [
        "Low",
        "Moderate",
        "High",
        "Not specified",
    ],
    "Trend": [
        "Increasing",
        "Stable",
        "Decreasing",
        "Not specified",
    ],
    "Language certainty": [
        "Confident",
        "Uncertain",
        "Mixed",
        "Unclear",
    ],
}

FIELDS = {
    "Mentions": "mention_count",
    "Level": "level",
    "Trend": "trend",
    "Language certainty": "language_certainty",
}

DESCRIPTIONS = {
    "Mentions": "How many times is this indicator mentioned?",
    "Level": "What level is described?",
    "Trend": "How is the indicator changing?",
    "Language certainty": (
        "Confident = asserted; Uncertain = might/may/could; "
        "Mixed = both; Unclear = cannot determine."
    ),
}


# ============================================================
# DATA AND PROGRESS
# ============================================================

def utc_now():
    return datetime.now(timezone.utc).isoformat()


def valid_email(email):
    return bool(
        re.fullmatch(
            r"[^\s@]+@[^\s@]+\.[^\s@]+",
            email.strip(),
        )
    )


def load_statements():
    if not RAW_EXCEL.exists():
        raise ValueError(
            f"Cannot find {RAW_EXCEL.name}. "
            "Place it in the same folder as this Python script."
        )

    frame = pd.read_excel(
        RAW_EXCEL,
        sheet_name=STATEMENTS_SHEET,
        engine="openpyxl",
        keep_default_na=False,
    )

    frame.columns = frame.columns.astype(str).str.strip()

    frame = frame.rename(
        columns={
            "Statement ID": "id",
            "Meeting date": "date",
            "Full statement text": "text",
            "Source URL": "source_url",
        }
    )

    required = {"id", "date", "text"}
    missing = required - set(frame.columns)

    if missing:
        raise ValueError(
            "The Excel sheet must contain Statement ID, "
            "Meeting date, and Full statement text. "
            "Missing mapped columns: "
            + ", ".join(sorted(missing))
        )

    columns = ["id", "date", "text"]

    if "source_url" in frame.columns:
        columns.append("source_url")

    frame = frame[columns].copy()

    blank_rows = frame[["id", "date", "text"]].apply(
        lambda column: column.astype(str).str.strip().eq("")
    ).all(axis=1)

    frame = frame.loc[~blank_rows].copy()

    for column in ("id", "text"):
        frame[column] = frame[column].astype(str).str.strip()

    if "source_url" not in frame.columns:
        frame["source_url"] = ""
    else:
        frame["source_url"] = (
            frame["source_url"].astype(str).str.strip()
        )

    if len(frame) != len(SELECTED_IDS):
        raise ValueError(
            f"The Excel sheet contains {len(frame)} statements; "
            f"exactly {len(SELECTED_IDS)} are required."
        )

    if frame["id"].eq("").any():
        raise ValueError("Every statement must have an ID.")

    if frame["id"].duplicated().any():
        raise ValueError("Each statement must have a unique ID.")

    if frame["text"].eq("").any():
        raise ValueError("Every statement must have full text.")

    actual_ids = set(frame["id"])
    expected_ids = set(SELECTED_IDS)

    if actual_ids != expected_ids:
        messages = []

        missing_ids = expected_ids - actual_ids
        unexpected_ids = actual_ids - expected_ids

        if missing_ids:
            messages.append(
                "Missing IDs: " + ", ".join(sorted(missing_ids))
            )

        if unexpected_ids:
            messages.append(
                "Unexpected IDs: "
                + ", ".join(sorted(unexpected_ids))
            )

        raise ValueError(
            "The Excel file does not match the selected statements. "
            + " ".join(messages)
        )

    dates = pd.to_datetime(
        frame["date"],
        errors="coerce",
        utc=True,
    )

    if dates.isna().any():
        raise ValueError(
            "Every statement must have a valid meeting date."
        )

    if (
        dates.dt.normalize()
        > pd.Timestamp.now(tz="UTC").normalize()
    ).any():
        raise ValueError(
            "Statement dates cannot be in the future."
        )

    frame["date"] = dates.dt.strftime("%Y-%m-%d")

    # Follow the order in the All 10 statements sheet.
    # The separate Reading view sheet is not used.
    return frame.to_dict("records")


def dataset_signature(statements):
    content = json.dumps(
        statements,
        sort_keys=True,
        ensure_ascii=False,
    )

    return hashlib.sha256(content.encode()).hexdigest()


def blank_draft():
    return {
        "start_timestamp": None,
        "choices": {},
        "details": {},
        "emphasis": {},
        "comments": "",
    }


def new_run(signature):
    return {
        "version": FORM_VERSION,
        "dataset_signature": signature,
        "run_id": str(uuid.uuid4()),
        "statement_index": 0,
        "coder_name": "",
        "coder_email": "",
        "intro_completed": False,
        "draft": blank_draft(),
    }


def check_progress_file(payload, signature, total):
    if not isinstance(payload, dict):
        raise ValueError("Invalid progress file.")

    if (
        payload.get("version") != FORM_VERSION
        or payload.get("dataset_signature") != signature
    ):
        raise ValueError(
            "This progress file does not match this form "
            "and statement set."
        )

    uuid.UUID(payload["run_id"])

    index = payload["statement_index"]

    if type(index) is not int or not 0 <= index <= total:
        raise ValueError("Invalid statement position.")

    for field in ("coder_name", "coder_email"):
        if not isinstance(payload.get(field), str):
            raise ValueError("Invalid coder information.")

    if type(payload.get("intro_completed")) is not bool:
        raise ValueError("Invalid first-page status.")

    draft = payload["draft"]

    if not isinstance(draft, dict):
        raise ValueError("Invalid draft.")

    comments = draft.get("comments", "")

    if not isinstance(comments, str) or len(comments) > 10_000:
        raise ValueError(
            "Invalid comments (maximum 10,000 characters)."
        )

    start = draft.get("start_timestamp")

    if start is not None:
        if not isinstance(start, str):
            raise ValueError("Invalid start timestamp.")

        parsed = datetime.fromisoformat(start)

        if parsed.tzinfo is None:
            raise ValueError(
                "The start timestamp must include a timezone."
            )

    for field in ("choices", "details", "emphasis"):
        if not isinstance(draft.get(field), dict):
            raise ValueError(f"Invalid {field} answers.")

        if not set(draft[field]).issubset(INDICATORS):
            raise ValueError(
                "Unknown indicator in progress file."
            )

    for value in draft["choices"].values():
        if value is not None and value not in (
            "Present",
            "Not present",
        ):
            raise ValueError("Invalid presence answer.")

    for value in draft["emphasis"].values():
        if value is not None and value not in EMPHASIS_OPTIONS:
            raise ValueError("Invalid emphasis answer.")

    for answers in draft["details"].values():
        if (
            not isinstance(answers, dict)
            or not set(answers).issubset(FIELDS)
        ):
            raise ValueError("Invalid indicator details.")

        count = answers.get("Mentions", 0)

        if type(count) is not int or not 0 <= count <= 1_000_000:
            raise ValueError("Invalid mention count.")

        for field, options in OPTIONS.items():
            value = answers.get(field)

            if value is not None and value not in options:
                raise ValueError(
                    f"Invalid {field.lower()} answer."
                )

    return {
        "version": FORM_VERSION,
        "dataset_signature": signature,
        "run_id": payload["run_id"],
        "statement_index": index,
        "coder_name": payload["coder_name"],
        "coder_email": payload["coder_email"],
        "intro_completed": payload["intro_completed"],
        "draft": {
            "start_timestamp": start,
            "choices": draft["choices"],
            "details": draft["details"],
            "emphasis": draft["emphasis"],
            "comments": comments,
        },
    }


def resume_panel(signature, total):
    with st.expander("Resume saved progress"):
        uploaded = st.file_uploader(
            "Upload your progress file",
            type=["json"],
            key="progress_upload",
        )

        if st.button("Restore progress"):
            if uploaded is None:
                st.error("Choose a progress file first.")
                return

            try:
                if uploaded.size > 1_000_000:
                    raise ValueError(
                        "This progress file is too large."
                    )

                payload = json.loads(uploaded.getvalue())

                restored = check_progress_file(
                    payload,
                    signature,
                    total,
                )

            except (
                ValueError,
                TypeError,
                KeyError,
                AttributeError,
                OverflowError,
            ) as exc:
                st.error(f"Cannot restore progress: {exc}")
                return

            st.session_state["_pending_run"] = restored
            st.rerun()


def save_progress_button(run):
    checkpoint = {
        **run,
        "saved_at": utc_now(),
    }

    st.caption(
        "To pause, download your progress before leaving. "
        "Upload the file under Resume saved progress "
        "when you return."
    )

    st.download_button(
        "Save progress — download file",
        data=json.dumps(
            checkpoint,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
        ),
        file_name="fomc_coding_progress.json",
        mime="application/json",
        on_click="ignore",
        key="download_progress",
    )


# ============================================================
# VALIDATION
# ============================================================

def validate(name, email, choices, details, emphasis):
    errors = []

    if not name.strip():
        errors.append("Enter your name.")

    if not valid_email(email):
        errors.append("Enter a valid email address.")

    for indicator in INDICATORS:
        choice = choices.get(indicator)

        if choice not in ("Present", "Not present"):
            errors.append(
                f"{indicator}: choose Present or Not present."
            )
            continue

        if choice != "Present":
            continue

        answers = details.get(indicator, {})
        count = answers.get("Mentions")

        if type(count) is not int or count < 1:
            errors.append(
                f"{indicator}: enter a whole mention count "
                "of at least 1."
            )

        for field, options in OPTIONS.items():
            if answers.get(field) not in options:
                errors.append(
                    f"{indicator}: answer {field.lower()}."
                )

        if emphasis.get(indicator) not in EMPHASIS_OPTIONS:
            errors.append(
                f"{indicator}: choose Low or High emphasis."
            )

    return errors


# ============================================================
# RESIZABLE PANELS
# ============================================================

SPLIT_JS = r"""
export default function() {
    let row, left, right, handle;

    let fraction = Number(
        sessionStorage.getItem('sampling-form-split') || 0.65
    );

    fraction = Math.min(0.8, Math.max(0.3, fraction));

    const apply = () => {
        if (!row) return;

        left.style.setProperty(
            'flex',
            `0 0 calc(${fraction * 100}% - 7px)`,
            'important'
        );

        right.style.setProperty(
            'flex',
            '1 1 0px',
            'important'
        );

        for (const panel of [left, right]) {
            panel.style.setProperty(
                'min-width', '0', 'important'
            );
            panel.style.setProperty(
                'width', '0', 'important'
            );
        }

        handle.setAttribute(
            'aria-valuenow',
            Math.round(fraction * 100)
        );
    };

    const save = () => sessionStorage.setItem(
        'sampling-form-split',
        fraction
    );

    const move = e => {
        const rect = row.getBoundingClientRect();

        fraction = Math.min(
            0.8,
            Math.max(
                0.3,
                (e.clientX - rect.left) / rect.width
            )
        );

        apply();
    };

    const end = e => {
        if (handle.hasPointerCapture(e.pointerId)) {
            handle.releasePointerCapture(e.pointerId);
        }

        handle.removeEventListener('pointermove', move);
        save();
    };

    const attach = () => {
        const host = document.querySelector(
            '.st-key-split_panels'
        );

        const next = host?.querySelector(
            '[data-testid="stHorizontalBlock"]'
        );

        if (!next || (next === row && handle?.isConnected)) {
            return;
        }

        const panels = [...next.children].filter(
            el => el.matches('[data-testid="stColumn"]')
        );

        if (panels.length !== 2) return;

        handle?.remove();

        row = next;
        [left, right] = panels;

        handle = document.createElement('div');
        handle.className = 'sampling-split-handle';

        handle.setAttribute('role', 'separator');
        handle.setAttribute(
            'aria-label',
            'Resize form and statement panels'
        );
        handle.setAttribute(
            'aria-orientation',
            'vertical'
        );
        handle.setAttribute('aria-valuemin', '30');
        handle.setAttribute('aria-valuemax', '80');

        handle.tabIndex = 0;
        handle.title = (
            'Drag to resize panels. Arrow keys also work.'
        );

        handle.addEventListener('pointerdown', e => {
            e.preventDefault();
            handle.setPointerCapture(e.pointerId);
            handle.addEventListener('pointermove', move);
        });

        handle.addEventListener('pointerup', end);
        handle.addEventListener('pointercancel', end);

        handle.addEventListener('keydown', e => {
            if (![
                'ArrowLeft',
                'ArrowRight',
                'Home',
                'End'
            ].includes(e.key)) {
                return;
            }

            e.preventDefault();

            fraction = e.key === 'Home'
                ? 0.3
                : e.key === 'End'
                ? 0.8
                : Math.min(
                    0.8,
                    Math.max(
                        0.3,
                        fraction + (
                            e.key === 'ArrowRight'
                            ? 0.02
                            : -0.02
                        )
                    )
                );

            apply();
            save();
        });

        row.style.setProperty(
            'gap', '0px', 'important'
        );
        row.style.setProperty(
            'flex-wrap', 'nowrap', 'important'
        );

        row.insertBefore(handle, right);
        apply();
    };

    const observer = new MutationObserver(attach);

    observer.observe(
        document.body,
        {childList: true, subtree: true}
    );

    attach();

    return () => {
        observer.disconnect();
        handle?.remove();
    };
}
"""

split_divider = st.components.v2.component(
    "sampling_split_divider",
    js=SPLIT_JS,
)


# ============================================================
# APP
# ============================================================

def main():
    st.set_page_config(
        page_title="FOMC Manual Coding",
        layout="wide",
        initial_sidebar_state="collapsed",
    )

    # Do not hide stElementToolbar: it may contain input elements.
    st.markdown(
        """
        <style>
        .block-container {
            max-width: 100%;
            padding: 2rem 1rem 1rem;
        }

        html, body, .stApp, input, textarea, button, label,
        h1, h2, h3, p,
        [data-testid="stMarkdownContainer"],
        [data-testid="stText"] {
            font-family: Arial, Helvetica, sans-serif !important;
        }

        [data-testid="stText"] {
            white-space: pre-wrap;
            line-height: 1.65;
            font-size: 16px;
        }

        .sampling-split-handle {
            flex: 0 0 14px;
            align-self: stretch;
            min-height: 800px;
            cursor: col-resize;
            touch-action: none;
            position: relative;
            border-radius: 6px;
            background: linear-gradient(
                to right,
                transparent 6px,
                #a0a7b4 6px,
                #a0a7b4 8px,
                transparent 8px
            );
        }

        .sampling-split-handle:hover,
        .sampling-split-handle:focus-visible {
            background-color: rgba(100, 130, 190, 0.18);
            outline: 2px solid #7186ad;
        }

        .st-key-detail_scroll {
            overflow-x: auto !important;
            max-width: 100%;
            padding-bottom: 12px;
        }

        .st-key-detail_canvas {
            flex-shrink: 0 !important;
        }

        [data-testid="stTextArea"] textarea {
            border: 1px solid #8b95a5 !important;
            border-radius: 6px !important;
            min-height: 150px !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    owner_download_panel()

    st.title("FOMC Manual Coding")

    try:
        statements = load_statements()

    except (
        OSError,
        ValueError,
        ImportError,
        BadZipFile,
    ) as exc:
        st.error(
            f"Cannot load the selected statements: {exc}"
        )
        st.stop()

    signature = dataset_signature(statements)

    # Restore before creating coder or answer widgets.
    pending = st.session_state.pop("_pending_run", None)

    if pending is not None:
        for state_key in list(st.session_state):
            if (
                isinstance(state_key, str)
                and state_key.startswith("coding:")
            ):
                del st.session_state[state_key]

        st.session_state["coding_run"] = pending
        st.session_state["coder_name"] = pending["coder_name"]
        st.session_state["coder_email"] = pending["coder_email"]
        st.session_state["_coding_message"] = "Progress restored."

    if "coding_run" not in st.session_state:
        st.session_state["coding_run"] = new_run(signature)

    run = st.session_state["coding_run"]

    if (
        run.get("version") != FORM_VERSION
        or run.get("dataset_signature") != signature
    ):
        st.error(
            "The form or statement dataset changed. "
            "Open a new browser session to start "
            "with the updated version."
        )
        st.stop()

    resume_panel(signature, len(statements))

    message = st.session_state.pop(
        "_coding_message",
        None,
    )

    if message:
        st.success(message)

    index = run["statement_index"]
    total = len(statements)

    st.progress(
        index / total,
        text=f"{index} of {total} statements completed",
    )

    if index == total:
        st.success(
            f"All {total} statements are complete. Thank you!"
        )
        save_progress_button(run)
        st.stop()

    # --------------------------------------------------------
    # FIRST PAGE: CODER INFORMATION AND INSTRUCTIONS
    # --------------------------------------------------------

    if not run["intro_completed"]:
        st.subheader("Coder information and instructions")

        st.markdown(
            f"You will manually code {total} FOMC statements. "
            "For each statement, identify which inflation "
            "indicators are present, describe each present "
            "indicator, and assess whether it is central "
            "to the statement."
        )

        st.markdown(
            "**Instructions**\n\n"
            "- Do not use AI to complete the coding.\n"
            "- Refer to the training form for coding "
            "definitions and examples.\n"
            "- Answer all required questions for each statement.\n"
            "- Add optional comments after Section 3 "
            "if clarification is needed.\n"
            "- Download your progress before leaving "
            "if you need to pause."
        )

        st.session_state.setdefault(
            "coder_name",
            run["coder_name"],
        )
        st.session_state.setdefault(
            "coder_email",
            run["coder_email"],
        )

        run["coder_name"] = st.text_input(
            "Name *",
            key="coder_name",
        )

        run["coder_email"] = st.text_input(
            "Email *",
            key="coder_email",
        )

        if st.button("Start coding", type="primary"):
            if not run["coder_name"].strip():
                st.error("Enter your name.")

            elif not valid_email(run["coder_email"]):
                st.error("Enter a valid email address.")

            else:
                run["intro_completed"] = True
                st.rerun()

        save_progress_button(run)
        st.stop()

    statement = statements[index]
    draft = run["draft"]

    draft.setdefault("comments", "")

    # Give each statement its own widget keys.
    prefix = f"coding:{run['run_id']}:{statement['id']}"

    def key(field):
        return f"{prefix}:{field}"

    def record_start():
        if draft["start_timestamp"] is None:
            draft["start_timestamp"] = utc_now()

    def record_comments():
        # Save the latest text before the page reruns.
        draft["comments"] = st.session_state.get(
            key("comments"),
            "",
        )
        record_start()

    st.subheader(
        f"Statement {index + 1} of {total}"
    )

    st.caption(
        "Drag the divider between the form and statement "
        "to adjust their widths."
    )

    with st.container(key="split_panels"):
        left, right = st.columns(
            [0.65, 0.35],
            gap="small",
        )

    # --------------------------------------------------------
    # RIGHT PANEL: STATEMENT TEXT
    # --------------------------------------------------------

    with right:
        st.subheader("Assigned statement")

        st.caption(
            f"Meeting/date: {statement['date']} | "
            f"ID: {statement['id']}"
        )

        with st.container(height=800, border=True):
            st.text(statement["text"])

    # --------------------------------------------------------
    # LEFT PANEL: CODING FORM
    # --------------------------------------------------------

    with left:
        with st.container(
            height=880,
            border=True,
            key=f"coding_panel_{index}",
        ):
            name = run["coder_name"]
            email = run["coder_email"]

            st.caption(f"Coder: {name} | {email}")

            if st.button(
                "Edit coder information",
                key=key("edit_coder"),
            ):
                run["intro_completed"] = False
                st.rerun()

            # ------------------------------------------------
            # SECTION 1: PRESENCE
            # ------------------------------------------------

            st.divider()
            st.subheader("1. Is each indicator present?")

            st.caption(
                "Choose Present or Not present "
                "for every indicator."
            )

            choices = draft["choices"]
            presence_options = ["Present", "Not present"]

            for indicator in INDICATORS:
                label_column, answer_column = st.columns(
                    [1, 2]
                )

                with label_column:
                    st.markdown(f"**{indicator}**")
                    st.caption(
                        INDICATOR_DESCRIPTIONS[indicator]
                    )

                with answer_column:
                    previous = choices.get(indicator)

                    choices[indicator] = st.radio(
                        f"{indicator}: presence",
                        presence_options,
                        index=(
                            presence_options.index(previous)
                            if previous in presence_options
                            else None
                        ),
                        horizontal=True,
                        label_visibility="collapsed",
                        key=key(f"presence:{indicator}"),
                        on_change=record_start,
                    )

            present = [
                indicator
                for indicator in INDICATORS
                if choices.get(indicator) == "Present"
            ]

            # ------------------------------------------------
            # SECTION 2: INDICATOR DETAILS
            # ------------------------------------------------

            st.divider()
            st.subheader("2. Indicators")

            st.caption(
                "Complete each row for the present indicators. "
                "Scroll horizontally to see all questions."
            )

            details = draft["details"]

            if present:
                widths = [200, 170, 190, 190, 260]
                table_width = sum(widths)

                st.markdown(
                    f"""
                    <style>
                    .st-key-detail_canvas {{
                        width: {table_width}px !important;
                        min-width: {table_width}px !important;
                        max-width: none !important;
                    }}
                    </style>
                    """,
                    unsafe_allow_html=True,
                )

                with st.container(
                    border=True,
                    key="detail_scroll",
                ):
                    with st.container(
                        width=table_width,
                        key="detail_canvas",
                    ):
                        headers = st.columns(widths)

                        with headers[0]:
                            st.markdown("**Indicator**")

                        for column, field in zip(
                            headers[1:],
                            FIELDS,
                        ):
                            with column:
                                st.markdown(f"**{field}** *")
                                st.caption(
                                    DESCRIPTIONS[field]
                                )

                        st.divider()

                        for indicator in present:
                            cells = st.columns(widths)

                            answers = details.setdefault(
                                indicator,
                                {},
                            )

                            with cells[0]:
                                st.markdown(
                                    f"**{indicator}**"
                                )

                            for column, field in zip(
                                cells[1:],
                                FIELDS,
                            ):
                                with column:
                                    old_value = answers.get(
                                        field
                                    )

                                    if field == "Mentions":
                                        answers[field] = (
                                            st.number_input(
                                                f"{indicator}: {field}",
                                                min_value=0,
                                                max_value=1_000_000,
                                                step=1,
                                                value=(
                                                    old_value
                                                    if old_value is not None
                                                    else 0
                                                ),
                                                key=key(
                                                    f"detail:{indicator}:{field}"
                                                ),
                                                label_visibility="collapsed",
                                                on_change=record_start,
                                                help=DESCRIPTIONS[field],
                                            )
                                        )

                                    else:
                                        options = OPTIONS[field]

                                        answers[field] = (
                                            st.selectbox(
                                                f"{indicator}: {field}",
                                                options,
                                                index=(
                                                    options.index(old_value)
                                                    if old_value in options
                                                    else None
                                                ),
                                                key=key(
                                                    f"detail:{indicator}:{field}"
                                                ),
                                                label_visibility="collapsed",
                                                on_change=record_start,
                                                help=DESCRIPTIONS[field],
                                            )
                                        )

            else:
                st.info(
                    "Indicators marked Present in section 1 "
                    "will appear here."
                )

            # ------------------------------------------------
            # SECTION 3: EMPHASIS
            # ------------------------------------------------

            st.divider()
            st.subheader("3. Emphasis")

            emphasis = draft["emphasis"]

            if present:
                with st.container(border=True):
                    headers = st.columns([1, 2])

                    with headers[0]:
                        st.markdown("**Indicator**")

                    with headers[1]:
                        st.markdown("**Emphasis level**")
                        st.caption(
                            "Is this indicator a central "
                            "part of the statement? "
                            "High = central; Low = peripheral."
                        )

                    st.divider()

                    for indicator in present:
                        cells = st.columns([1, 2])

                        with cells[0]:
                            st.markdown(
                                f"**{indicator}**"
                            )

                        with cells[1]:
                            previous = emphasis.get(
                                indicator
                            )

                            emphasis[indicator] = st.radio(
                                f"{indicator}: emphasis level",
                                EMPHASIS_OPTIONS,
                                index=(
                                    EMPHASIS_OPTIONS.index(previous)
                                    if previous in EMPHASIS_OPTIONS
                                    else None
                                ),
                                horizontal=True,
                                label_visibility="collapsed",
                                key=key(f"emphasis:{indicator}"),
                                on_change=record_start,
                            )

                        st.divider()

            else:
                st.info(
                    "Indicators marked Present in section 1 "
                    "will appear here."
                )

            # ------------------------------------------------
            # OPTIONAL COMMENTS
            # ------------------------------------------------

            st.divider()
            st.subheader("Comments (optional)")

            with st.container(border=True):
                st.caption(
                    "Use this box to explain uncertain coding "
                    "decisions or add any other notes. "
                    "You may leave it blank."
                )

                comments_key = key("comments")

                if comments_key not in st.session_state:
                    st.session_state[comments_key] = (
                        draft.get("comments", "")
                    )

                draft["comments"] = st.text_area(
                    "Any comments about this statement or your coding?",
                    height=180,
                    max_chars=10_000,
                    placeholder="Type your comments here...",
                    key=comments_key,
                    on_change=record_comments,
                    label_visibility="visible",
                )

            # ------------------------------------------------
            # SAVE PROGRESS AND SUBMIT
            # ------------------------------------------------

            st.divider()
            save_progress_button(run)

            errors = validate(
                name,
                email,
                choices,
                details,
                emphasis,
            )

            if (
                st.session_state.get(key("show_errors"))
                and errors
            ):
                st.error(
                    "Please complete the following:\n\n"
                    + "\n\n".join(
                        "• " + error
                        for error in errors
                    )
                )

            button_label = (
                "Submit and open next statement"
                if index < total - 1
                else "Submit final statement"
            )

            if st.button(
                button_label,
                type="primary",
                key=key("submit"),
            ):
                if errors:
                    st.session_state[
                        key("show_errors")
                    ] = True
                    st.rerun()

                record_start()
                end_timestamp = utc_now()

                # Stable across retries and restored progress.
                submission_id = str(
                    uuid.uuid5(
                        uuid.UUID(run["run_id"]),
                        statement["id"],
                    )
                )

                response = {
                    "submission_id": submission_id,
                    "run_id": run["run_id"],
                    "form_version": FORM_VERSION,
                    "statement_number": index + 1,
                    "start_timestamp": draft["start_timestamp"],
                    "end_timestamp": end_timestamp,
                    "timestamp": end_timestamp,
                    "coder_name": name.strip(),
                    "coder_email": email.strip(),
                    "statement_id": statement["id"],
                    "meeting_date": statement["date"],
                    "source_excel": RAW_EXCEL.name,
                    "source_sheet": STATEMENTS_SHEET,
                    "source_url": statement.get(
                        "source_url",
                        "",
                    ),
                    "comments": draft["comments"].strip(),
                }

                for indicator in INDICATORS:
                    field_prefix = indicator.replace(
                        " ",
                        "_",
                    )

                    is_present = indicator in present

                    response[
                        field_prefix + "_present"
                    ] = choices[indicator]

                    response[
                        field_prefix + "_emphasis_level"
                    ] = (
                        emphasis.get(indicator, "")
                        if is_present
                        else ""
                    )

                    for column, field in FIELDS.items():
                        value = (
                            details[indicator][column]
                            if is_present
                            else ""
                        )

                        if (
                            is_present
                            and column == "Mentions"
                        ):
                            value = int(value)

                        response[
                            field_prefix + "_" + field
                        ] = value

                try:
                    save_cloud_response(
                        response,
                        submission_id,
                    )

                except (StorageError, OSError) as exc:
                    st.error(
                        f"Could not submit: {exc}. "
                        "Your answers remain available. "
                        "Retry or download your progress."
                    )

                else:
                    # Advance only after saving succeeds.
                    run["statement_index"] = index + 1
                    run["draft"] = blank_draft()

                    st.session_state[
                        "_coding_message"
                    ] = (
                        f"Statement {index + 1} "
                        "submitted successfully."
                    )

                    st.rerun()

    split_divider(key="split_divider")


if __name__ == "__main__":
    main()
