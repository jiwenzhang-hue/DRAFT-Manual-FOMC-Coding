from pathlib import Path
from datetime import datetime, timezone
import csv
import hashlib
import os
import re
import threading
import uuid
from cloud_storage import save_cloud_response, owner_download_panel, StorageError

import pandas as pd
import streamlit as st


# ============================================================
# ADMINISTRATOR SETTINGS
# Responders cannot change these in the app.
# ============================================================

# Choose the dataset and assigned statement here.
SAMPLING_FOLDER = Path(__file__).resolve().parent
DATASET_FILE = "fomc_statements_cleaned.csv"
ASSIGNED_STATEMENT_ID = "statement_20000202"
RAW_CSV = SAMPLING_FOLDER / DATASET_FILE
# Set these to the column names in the selected CSV.
ID_COLUMN = "id"
DATE_COLUMN = "date"
TEXT_COLUMN = "text"

OUTPUT_CSV = (
    Path(__file__).resolve().parent
    / "manual_coding_responses.csv"
)


# ============================================================
# INDICATORS AND ANSWER OPTIONS
# ============================================================

INDICATORS = [
    "Core Inflation",
    "Core CPI",
    "Core PCE",
    "Headline Inflation",
    "Headline CPI",
    "Headline PCE",
    "Services",
    "Goods",
    "Housing",
    "Energy",
    "Food",
    "PPI",
    "Wage Inflation",
    "Inflation Expectations",
    "Commodity Prices",
    "General Inflation",
]

OPTIONS = {
    "Level": ["Low", "Moderate", "High", "Not specified"],
    "Trend": ["Increasing", "Stable", "Decreasing", "Not specified"],
    "Adjective strength": ["Strong", "Weak", "Mixed", "Not specified"],
    "Language certainty": ["Confident", "Uncertain", "Mixed", "Unclear"],
}
FIELDS = {
    "Mentions": "mention_count",
    "Level": "level",
    "Trend": "trend",
    "Adjective strength": "adjective_strength",
    "Language certainty": "language_certainty",
}
DESCRIPTIONS = {
    "Mentions": "How many times is this indicator mentioned?",
    "Level": "What level of the indicator is described?",
    "Trend": "How is the indicator changing?",
    "Adjective strength": "Assess the adjectives describing the indicator: strong, weak, both, or none specified.",
    "Language certainty": "How is the indicator talked about? Confident = asserted; Uncertain = might/may/could be; Mixed = both; Unclear = cannot determine.",
}



# ============================================================
# VALIDATION
# ============================================================

def validate(name, email, choices, details):
    errors = []

    if not name.strip():
        errors.append("Enter your name.")

    if not re.fullmatch(
        r"[^\s@]+@[^\s@]+\.[^\s@]+",
        email.strip(),
    ):
        errors.append("Enter a valid email address.")

    for indicator, choice in choices.items():
        if choice not in ("Present", "Not present"):
            errors.append(
                f"{indicator}: select exactly one of "
                "Present or Not present."
            )

    present = [
        indicator
        for indicator in INDICATORS
        if choices[indicator] == "Present"
    ]

    for indicator in present:
        answers = details.get(indicator, {})
        count = answers.get("Mentions")

        if (
            count is None
            or pd.isna(count)
            or float(count) < 1
            or not float(count).is_integer()
        ):
            errors.append(
                f"{indicator}: enter a whole mention "
                "count of at least 1."
            )

        for field, options in OPTIONS.items():
            if answers.get(field) not in options:
                errors.append(
                    f"{indicator}: answer {field.lower()}."
                )

    return errors


# ============================================================
# SAVE RESPONSES
# ============================================================

def save_response(response):
    try:
        save_cloud_response(response, response['submission_id'])
    except StorageError as exc:
        raise OSError(str(exc)) from None
    return None


# ============================================================
# LOAD ASSIGNED STATEMENT
# ============================================================

def load_statement():
    frame = pd.read_csv(
        RAW_CSV,
        dtype=str,
        keep_default_na=False,
    )

    source_columns = [ID_COLUMN, DATE_COLUMN, TEXT_COLUMN]
    if len(set(source_columns)) != 3:
        raise ValueError("ID_COLUMN, DATE_COLUMN, and TEXT_COLUMN must be different.")
    missing = set(source_columns) - set(frame.columns)
    if missing:
        raise ValueError("Missing CSV columns: " + ", ".join(sorted(missing)))
    frame = frame[source_columns].copy()
    frame.columns = ["id", "date", "text"]
    required = {"id", "date", "text"}

    if not required.issubset(frame.columns):
        missing = required - set(frame.columns)

        raise ValueError(
            "The raw-text CSV is missing: "
            + ", ".join(sorted(missing))
        )

    assigned = frame[
        frame["id"].str.strip()
        == ASSIGNED_STATEMENT_ID
    ]

    if len(assigned) != 1:
        raise ValueError(
            f"Assigned ID '{ASSIGNED_STATEMENT_ID}' must "
            "match exactly one CSV row. "
            "Check ASSIGNED_STATEMENT_ID in the code."
        )

    statement = assigned.iloc[0]

    if not statement["text"].strip():
        raise ValueError(
            "The assigned statement has no full text."
        )

    return statement


SPLIT_JS = r"""
export default function() {
    let row, left, right, handle;
    let fraction = Number(sessionStorage.getItem('sampling-form-split') || 0.65);
    fraction = Math.min(0.8, Math.max(0.3, fraction));
    const apply = () => {
        if (!row) return;
        left.style.setProperty('flex', `0 0 calc(${fraction * 100}% - 7px)`, 'important');
        right.style.setProperty('flex', '1 1 0px', 'important');
        for (const panel of [left, right]) {
            panel.style.setProperty('min-width', '0', 'important');
            panel.style.setProperty('width', '0', 'important');
        }
        handle.setAttribute('aria-valuenow', Math.round(fraction * 100));
    };
    const save = () => sessionStorage.setItem('sampling-form-split', fraction);
    const move = e => {
        const rect = row.getBoundingClientRect();
        fraction = Math.min(0.8, Math.max(0.3, (e.clientX - rect.left) / rect.width));
        apply();
    };
    const end = e => {
        if (handle.hasPointerCapture(e.pointerId)) handle.releasePointerCapture(e.pointerId);
        handle.removeEventListener('pointermove', move);
        save();
    };
    const attach = () => {
        const host = document.querySelector('.st-key-split_panels');
        const next = host?.querySelector('[data-testid="stHorizontalBlock"]');
        if (!next || (next === row && handle?.isConnected)) return;
        const panels = [...next.children].filter(el => el.matches('[data-testid="stColumn"]'));
        if (panels.length !== 2) return;
        row = next; [left, right] = panels;
        handle = document.createElement('div');
        handle.className = 'sampling-split-handle';
        handle.setAttribute('role', 'separator');
        handle.setAttribute('aria-label', 'Resize form and statement panels');
        handle.setAttribute('aria-orientation', 'vertical');
        handle.setAttribute('aria-valuemin', '30');
        handle.setAttribute('aria-valuemax', '80');
        handle.tabIndex = 0;
        handle.title = 'Drag to resize panels. Use arrow keys when focused.';
        handle.addEventListener('pointerdown', e => {
            e.preventDefault();
            handle.setPointerCapture(e.pointerId);
            handle.addEventListener('pointermove', move);
        });
        handle.addEventListener('pointerup', end);
        handle.addEventListener('pointercancel', end);
        handle.addEventListener('keydown', e => {
            if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) return;
            e.preventDefault();
            fraction = e.key === 'Home' ? 0.3 : e.key === 'End' ? 0.8 :
                Math.min(0.8, Math.max(0.3, fraction + (e.key === 'ArrowRight' ? 0.02 : -0.02)));
            apply(); save();
        });
        row.style.setProperty('gap', '0px', 'important');
        row.style.setProperty('flex-wrap', 'nowrap', 'important');
        row.insertBefore(handle, right);
        apply();
    };
    const observer = new MutationObserver(attach);
    observer.observe(document.body, {childList: true, subtree: true});
    attach();
    return () => { observer.disconnect(); handle?.remove(); };
}
"""

split_divider = st.components.v2.component("sampling_split_divider", js=SPLIT_JS)

# ============================================================
# APP
# ============================================================

def main():
    st.set_page_config(
        page_title="FOMC Manual Coding",
        layout="wide",
        initial_sidebar_state="collapsed",
    )

    st.markdown(
        """
        <style>
        /* Reduce the outer margins. */
        .block-container {
            max-width: 100%;
            padding-left: 1rem;
            padding-right: 1rem;
            padding-top: 2rem;
            padding-bottom: 1rem;
        }

        /* Arial font. */
        html, body, .stApp, input, button, label,
        h1, h2, h3, p,
        [data-testid="stMarkdownContainer"],
        [data-testid="stText"] {
            font-family: Arial, Helvetica, sans-serif !important;
        }

        /* Statement text. */
        [data-testid="stText"] {
            white-space: pre-wrap;
            line-height: 1.65;
            font-size: 16px;
        }

        /* Hide table visibility, download, and search controls. */
        [data-testid="stElementToolbar"] {
            display: none !important;
        }

        .sampling-split-handle {
            flex: 0 0 14px; align-self: stretch; min-height: 800px;
            cursor: col-resize; touch-action: none; position: relative;
            border-radius: 6px;
            background: linear-gradient(to right, transparent 6px, #a0a7b4 6px, #a0a7b4 8px, transparent 8px);
        }
        .sampling-split-handle:hover, .sampling-split-handle:focus-visible {
            background-color: rgba(100, 130, 190, 0.18);
            outline: 2px solid #7186ad;
        }
        /* Horizontal scrolling for the details table. */
        .st-key-detail_scroll {
            overflow-x: auto !important;
            max-width: 100%;
            padding-bottom: 12px;
        }

        .st-key-detail_canvas {
            flex-shrink: 0 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    owner_download_panel()
    st.title("FOMC Manual Coding")

    st.caption(
        "Complete all required responses for the assigned statement."
    )

    try:
        statement = load_statement()

    except (OSError, ValueError, pd.errors.ParserError) as exc:
        st.error(
            f"Cannot load the assigned statement: {exc}"
        )
        st.info(
            "Ask the administrator to check the CSV path "
            "and assigned statement ID in the code."
        )
        st.stop()

    scope = hashlib.sha256(
        (
            str(RAW_CSV)
            + ASSIGNED_STATEMENT_ID
            + statement["text"]
        ).encode()
    ).hexdigest()[:16]

    def key(field):
        return f"{scope}:{field}"

    def record_start():
        st.session_state.setdefault(key("start_timestamp"), datetime.now(timezone.utc).isoformat())

    st.caption("Drag the divider between the form and statement to adjust their widths.")
    with st.container(key="split_panels"):
        left, right = st.columns([0.65, 0.35], gap="small")

    # ========================================================
    # RIGHT PANEL — LOCKED STATEMENT
    # ========================================================

    with right:
        st.subheader("Assigned statement")

        st.caption(
            f"Meeting/date: {statement['date']} | "
            f"ID: {ASSIGNED_STATEMENT_ID}"
        )

        with st.container(height=800, border=True):
            st.text(statement["text"])

    # ========================================================
    # LEFT PANEL — CODING FORM
    # ========================================================

    with left:
        with st.container(height=880, border=True):
            st.subheader("Coder information")

            name_column, email_column = st.columns(2)

            with name_column:
                name = st.text_input(
                    "Name *",
                    key="coder_name",
                    on_change=record_start,
                )

            with email_column:
                email = st.text_input(
                    "Email *",
                    key="coder_email",
                    on_change=record_start,
                )

            st.divider()

            # =================================================
            # SECTION 1 — PRESENCE
            # One exclusive presence choice per indicator.
            # =================================================

            st.subheader("1. Is each indicator present?")

            st.caption("Choose Present or Not present for every indicator. General Inflation is last.")
            choices = {}
            for indicator in INDICATORS:
                label_column, answer_column = st.columns([1, 2])
                with label_column:
                    st.markdown(f"**{indicator}**")
                with answer_column:
                    choices[indicator] = st.radio(
                        f"{indicator}: presence",
                        ["Present", "Not present"],
                        index=None,
                        horizontal=True,
                        label_visibility="collapsed",
                        key=key(f"presence:{indicator}"),
                        on_change=record_start,
                    )

            present = [
                indicator
                for indicator in INDICATORS
                if choices[indicator] == "Present"
            ]

            st.divider()

            st.subheader("2. Indicators")
            st.caption("Complete each row for the present indicators. Scroll horizontally to see all questions.")
            saved = st.session_state.setdefault(key("details_saved"), {})
            if present:
                widths = [200, 170, 190, 190, 230, 260]
                table_width = sum(widths)
                st.markdown(
                    f"<style>.st-key-detail_canvas {{width:{table_width}px !important; min-width:{table_width}px !important; max-width:none !important;}}</style>",
                    unsafe_allow_html=True,
                )
                with st.container(border=True, key="detail_scroll"):
                    with st.container(width=table_width, key="detail_canvas"):
                        headers = st.columns(widths)
                        with headers[0]:
                            st.markdown("**Indicator**")
                        for column, field in zip(headers[1:], FIELDS):
                            with column:
                                st.markdown(f"**{field}** *")
                                st.caption(DESCRIPTIONS[field])
                        st.divider()
                        for indicator in present:
                            cells = st.columns(widths)
                            with cells[0]:
                                st.markdown(f"**{indicator}**")
                            previous = saved.setdefault(indicator, {})
                            for column, field in zip(cells[1:], FIELDS):
                                with column:
                                    answer_key = key(f"detail:{indicator}:{field}")
                                    old_value = previous.get(field)
                                    if field == "Mentions":
                                        value = st.number_input(
                                            f"{indicator}: {field}", min_value=0, step=1,
                                            value=int(old_value) if old_value is not None and pd.notna(old_value) else 0,
                                            key=answer_key, label_visibility="collapsed",
                                            on_change=record_start,
                                            help=DESCRIPTIONS[field],
                                        )
                                    else:
                                        options = OPTIONS[field]
                                        value = st.selectbox(
                                            f"{indicator}: {field}", options,
                                            index=options.index(old_value) if old_value in options else None,
                                            key=answer_key, label_visibility="collapsed",
                                            on_change=record_start,
                                            help=DESCRIPTIONS[field],
                                        )
                                    previous[field] = value
            else:
                st.info("Indicators marked Present in section 1 will appear here.")

            errors = validate(
                name,
                email,
                choices,
                saved,
            )

            if (
                st.session_state.get(
                    key("show_errors")
                )
                and errors
            ):
                st.error(
                    "Please complete the following:\n\n"
                    + "\n\n".join(
                        "• " + message
                        for message in errors
                    )
                )

            st.divider()

            # =================================================
            # SUBMIT — ONLY AT THE BOTTOM
            # =================================================

            if st.button(
                "Submit Coding",
                type="primary",
                key=key("submit"),
                disabled=st.session_state.get(key("submitted"), False),
            ):
                if errors:
                    st.session_state[
                        key("show_errors")
                    ] = True

                    st.rerun()

                else:
                    end_timestamp = datetime.now(timezone.utc).isoformat()
                    response = {
                        "submission_id": st.session_state.setdefault(key("submission_id"), str(uuid.uuid4())),
                        "start_timestamp": st.session_state[key("start_timestamp")],
                        "end_timestamp": end_timestamp,
                        "timestamp": end_timestamp,
                        "coder_name": name.strip(),
                        "coder_email": email.strip(),
                        "statement_id":
                            ASSIGNED_STATEMENT_ID,
                        "meeting_date": statement["date"],
                        "source_csv": str(RAW_CSV),
                    }

                    for indicator in INDICATORS:
                        prefix = indicator.replace(
                            " ",
                            "_",
                        )

                        response[
                            prefix + "_present"
                        ] = choices[indicator]

                        for column, field in FIELDS.items():
                            if indicator in present:
                                value = saved[
                                    indicator
                                ][column]

                                if column == "Mentions":
                                    value = int(value)

                            else:
                                value = ""

                            response[
                                prefix + "_" + field
                            ] = value

                    try:
                        save_response(response)
                        st.session_state[key("submitted")] = True

                        st.session_state[
                            key("show_errors")
                        ] = False

                        st.success("Coding submitted successfully. Your responses are saved in the online database.")
                    except OSError as exc:
                        st.error(
                            f"Could not save: {exc}. "
                            "Your answers remain available. "
                            "Ask the administrator to check "
                            "the database connection."
                        )

    split_divider(key="split_divider")


if __name__ == "__main__":
    main()
