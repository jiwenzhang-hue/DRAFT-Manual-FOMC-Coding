from pathlib import Path
from datetime import datetime, timezone
import hashlib
import re
import uuid

import pandas as pd
import streamlit as st


# ============================================================
# ADMINISTRATOR SETTINGS
# Responders cannot change these in the app.
# ============================================================

RAW_CSV = Path(__file__).resolve().parent / "fomc_statements_cleaned.csv"

# Change this ID to assign a different statement.
ASSIGNED_STATEMENT_ID = "statement_20000202"




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
    "Level": [
        "Low",
        "Moderate",
        "High",
        "Mixed",
        "Not specified",
    ],
    "Trend": [
        "Increasing",
        "Stable",
        "Decreasing",
        "Mixed",
        "Not specified",
    ],
    "Intensity": [
        "Low",
        "Moderate",
        "High",
    ],
    "Certainty": [
        "Asserted",
        "Hedged",
        "Mixed",
    ],
    "Emphasis": [
        "Weakly",
        "Moderately",
        "Strongly",
    ],
}

FIELDS = {
    "Mentions": "mention_count",
    "Level": "level",
    "Trend": "trend",
    "Intensity": "intensity",
    "Certainty": "certainty",
    "Emphasis": "emphasis",
}


# ============================================================
# VALIDATION
# ============================================================

def validate(name, email, choices, details, ranking):
    errors = []

    if not name.strip():
        errors.append("Enter your name.")

    if not re.fullmatch(
        r"[^\s@]+@[^\s@]+\.[^\s@]+",
        email.strip(),
    ):
        errors.append("Enter a valid email address.")

    for indicator, choice in choices.items():
        if choice is None:
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

    for index in range(min(3, len(present))):
        if (
            index >= len(ranking)
            or ranking[index] not in present
        ):
            errors.append(
                f"Select emphasis rank {index + 1}."
            )

        elif ranking[index] in ranking[:index]:
            errors.append(
                "Choose a different indicator for each rank."
            )

    return errors


# ============================================================
# SAVE RESPONSES
# ============================================================

def save_response(response):
    from sheets_storage import append_response
    append_response(response)


# ============================================================
# LOAD ASSIGNED STATEMENT
# ============================================================

def load_statement():
    frame = pd.read_csv(
        RAW_CSV,
        dtype=str,
        keep_default_na=False,
    )

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

    if st.session_state.get(key("submitted"), False):
        st.success("Your coding has been saved to Google Sheets. Thank you.")

    # Form: 65%. Statement: 35%.
    left, right = st.columns(
        [0.65, 0.35],
        gap="medium",
    )

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
                )

            with email_column:
                email = st.text_input(
                    "Email *",
                    key="coder_email",
                )

            st.divider()

            # =================================================
            # SECTION 1 — PRESENCE
            # One indicator per row; two answer columns.
            # =================================================

            st.subheader("1. Is each indicator present?")

            st.caption(
                "Check exactly one box in each row. "
                "General Inflation is last."
            )

            initial = pd.DataFrame(
                {
                    "Present": [False] * len(INDICATORS),
                    "Not present": [False] * len(INDICATORS),
                },
                index=pd.Index(
                    INDICATORS,
                    name="Indicator",
                ),
            )

            presence = st.data_editor(
                initial,
                key=key("presence_rows"),
                hide_index=False,
                disabled=["_index"],
                num_rows="fixed",
                height=600,
                width="stretch",
                column_config={
                    "_index": st.column_config.TextColumn(
                        "Indicator",
                        width="medium",
                    ),
                    "Present": st.column_config.CheckboxColumn(
                        "Present",
                        width="small",
                    ),
                    "Not present": st.column_config.CheckboxColumn(
                        "Not present",
                        width="small",
                    ),
                },
            )

            choices = {}
            both_selected = []

            for indicator in INDICATORS:
                yes = bool(
                    presence.loc[indicator, "Present"]
                )

                no = bool(
                    presence.loc[indicator, "Not present"]
                )

                if yes and no:
                    both_selected.append(indicator)

                if yes != no:
                    choices[indicator] = (
                        "Present" if yes else "Not present"
                    )
                else:
                    choices[indicator] = None

            if both_selected:
                st.warning(
                    "Select only one box for: "
                    + ", ".join(both_selected)
                )

            present = [
                indicator
                for indicator in INDICATORS
                if choices[indicator] == "Present"
            ]

            st.divider()

            # =================================================
            # SECTION 2 — ONE HORIZONTALLY SCROLLABLE TABLE
            # Indicators are columns; questions are rows.
            # =================================================

            st.subheader("2. Details for present indicators")

            st.caption(
                "Complete every answer. "
                "Scroll horizontally to see all present indicators."
            )

            saved = st.session_state.setdefault(
                key("details_saved"),
                {},
            )

            if present:
                question_width = 150
                indicator_width = 230

                table_width = (
                    question_width
                    + indicator_width * len(present)
                )

                # Keep the inner table wide instead of squeezing
                # indicator columns into the form panel.
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
                        widths = (
                            [question_width]
                            + [indicator_width] * len(present)
                        )

                        headers = st.columns(widths)

                        with headers[0]:
                            st.markdown("**Question**")

                        for column, indicator in zip(
                            headers[1:],
                            present,
                        ):
                            with column:
                                st.markdown(
                                    f"**{indicator}**"
                                )

                        st.divider()

                        for field in FIELDS:
                            cells = st.columns(widths)

                            with cells[0]:
                                st.markdown(
                                    f"**{field} \\***"
                                )

                            for column, indicator in zip(
                                cells[1:],
                                present,
                            ):
                                with column:
                                    previous = saved.setdefault(
                                        indicator,
                                        {},
                                    )

                                    answer_key = key(
                                        f"detail:{indicator}:{field}"
                                    )

                                    if field == "Mentions":
                                        old_value = previous.get(
                                            field
                                        )

                                        default = (
                                            int(old_value)
                                            if old_value is not None
                                            and pd.notna(old_value)
                                            else None
                                        )

                                        value = st.number_input(
                                            f"{indicator}: {field}",
                                            min_value=1,
                                            step=1,
                                            value=default,
                                            key=answer_key,
                                            label_visibility="collapsed",
                                        )

                                    else:
                                        options = OPTIONS[field]

                                        old_value = previous.get(
                                            field
                                        )

                                        default_index = (
                                            options.index(old_value)
                                            if old_value in options
                                            else None
                                        )

                                        help_text = None

                                        if field == "Certainty":
                                            help_text = (
                                                "Asserted = stated as fact "
                                                "or with high certainty. "
                                                "Hedged = qualified or "
                                                "uncertain. Mixed = both."
                                            )

                                        elif field == "Emphasis":
                                            help_text = (
                                                "Consider frequency of "
                                                "mentions and prominence "
                                                "in the discussion."
                                            )

                                        value = st.selectbox(
                                            f"{indicator}: {field}",
                                            options=options,
                                            index=default_index,
                                            key=answer_key,
                                            help=help_text,
                                            label_visibility="collapsed",
                                        )

                                    previous[field] = value

            else:
                st.info(
                    "Indicators marked Present in section 1 "
                    "will appear here."
                )

            st.divider()

            # =================================================
            # SECTION 3 — EMPHASIS RANKING
            # =================================================

            st.subheader("3. Emphasis ranking")

            ranking = []
            number_of_ranks = min(3, len(present))

            if present:
                st.caption(
                    f"Rank the {number_of_ranks} most emphasised "
                    "present indicators. "
                    "Rank 1 is the most emphasised."
                )

                rank_columns = st.columns(
                    number_of_ranks
                )

                for index, column in enumerate(rank_columns):
                    available = [
                        indicator
                        for indicator in present
                        if indicator not in ranking
                    ]

                    rank_key = key(
                        f"rank_{index + 1}"
                    )

                    if (
                        st.session_state.get(rank_key)
                        not in available
                    ):
                        st.session_state[rank_key] = None

                    with column:
                        selected_rank = st.selectbox(
                            f"Rank {index + 1} *",
                            options=available,
                            index=None,
                            key=rank_key,
                        )

                    ranking.append(selected_rank)

            else:
                st.caption(
                    "No ranking is needed when every "
                    "indicator is Not present."
                )

            errors = validate(
                name,
                email,
                choices,
                saved,
                ranking,
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
                    response = {
                        "timestamp": datetime.now(
                            timezone.utc
                        ).isoformat(),
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

                    for index in range(3):
                        response[
                            f"rank_{index + 1}"
                        ] = (
                            ranking[index]
                            if index < len(ranking)
                            else ""
                        )

                    try:
                        response["submission_id"] = st.session_state.setdefault(
                            key("submission_id"), str(uuid.uuid4())
                        )
                        save_response(response)

                        st.session_state[
                            key("show_errors")
                        ] = False

                        st.session_state[key("submitted")] = True
                        st.rerun()

                    except Exception:
                        st.error(
                            "We could not confirm your submission in Google Sheets. "
                            "Your answers are still here. Try Submit again; if this "
                            "continues, contact the administrator to check the "
                            "Google Sheets connection."
                        )



if __name__ == "__main__":
    main()