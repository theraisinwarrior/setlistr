"""Make date columns in on-screen tables sort as dates instead of as text.

Tables keep their dates as text (that's what snapshots and downloads store), so clicking a
date header used to sort alphabetically ("Apr" before "Aug" before "Dec"). For display,
recognized date columns are converted to real dates and shown in a friendly format.
"""
import pandas as pd

DATE_COLUMNS = {"Date", "Heard On", "Last Seen", "Last Played", "Last Time", "Your Last Time",
                "Their Last Time"}
# Order matters: 2-digit years first, so '01-10-26' isn't read as the year 26.
TEXT_FORMATS = [("%m-%d-%y", "MMM D, YYYY"), ("%m-%d-%Y", "MMM D, YYYY"), ("%b %d, %Y", "MMM D, YYYY"),
                ("%Y-%m-%d", "MMM D, YYYY"), ("%b %Y", "MMM YYYY")]


def sortable_dates(df: pd.DataFrame):
    """Return (copy with date columns as real dates, {column: display format})."""
    if df is None or df.empty:
        return df, {}
    out, formats = df.copy(), {}
    for col in [c for c in out.columns if c in DATE_COLUMNS]:
        s = out[col]
        if pd.api.types.is_datetime64_any_dtype(s):
            formats[col] = "MMM D, YYYY"
            continue
        present = int(s.notna().sum())
        if not present:
            continue
        text = s.astype("string")
        for fmt, shown in TEXT_FORMATS:
            parsed = pd.to_datetime(text, format=fmt, errors="coerce")
            if parsed.notna().sum() >= max(1, int(0.9 * present)):
                out[col], formats[col] = parsed, shown
                break
    return out, formats


def dated_table(data, column_config=None, **kwargs):
    """st.dataframe(), but date columns sort by date. Existing labels in column_config are kept."""
    import streamlit as st

    df, formats = sortable_dates(data)
    config = dict(column_config or {})
    for col, fmt in formats.items():
        label = config[col] if isinstance(config.get(col), str) else col
        config[col] = st.column_config.DateColumn(label, format=fmt)
    return st.dataframe(df, column_config=config, **kwargs)
