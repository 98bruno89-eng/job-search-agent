"""
dashboard/app.py — Streamlit dashboard for job-search-agent

View scored job matches, filter by score/location, click through to the
posting URL, and mark postings as applied — all from a browser, including
on your phone once this is deployed.

Run locally with:
    streamlit run dashboard/app.py
"""

import os
import re
import streamlit as st
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

st.set_page_config(page_title="Job Search Dashboard", layout="wide")

# --- Custom styling ---
st.markdown("""
<style>
    .block-container { padding-top: 2rem; max-width: 1100px; }

    .job-card {
        background: #232B27;
        border: 1px solid #33413B;
        border-radius: 10px;
        padding: 1.1rem 1.3rem;
        margin-bottom: 0.9rem;
    }
    .job-title {
        font-size: 1.05rem;
        font-weight: 600;
        color: #E8E6DF;
        margin-bottom: 0.15rem;
    }
    .job-meta {
        font-size: 0.82rem;
        color: #8FA39B;
        margin-bottom: 0.5rem;
    }
    .job-summary {
        font-size: 0.9rem;
        color: #C9C7BE;
        line-height: 1.45;
        margin-bottom: 0.5rem;
    }
    .score-badge {
        display: inline-block;
        font-weight: 700;
        font-size: 0.95rem;
        padding: 0.15rem 0.55rem;
        border-radius: 6px;
        margin-right: 0.5rem;
    }
    .score-high   { background: #2E5C4E; color: #A8E6C9; }
    .score-mid    { background: #5C4E2E; color: #E6C9A8; }
    .score-low    { background: #5C2E33; color: #E6A8AD; }

    /* Mobile: tighter padding, larger tap targets for buttons */
    @media (max-width: 640px) {
        .block-container { padding-left: 0.8rem; padding-right: 0.8rem; padding-top: 1rem; }
        .job-card { padding: 0.9rem 1rem; }
        .job-title { font-size: 0.98rem; }
        div[data-testid="stButton"] > button {
            width: 100%;
            padding-top: 0.55rem;
            padding-bottom: 0.55rem;
        }
    }
</style>
""", unsafe_allow_html=True)


def get_connection():
    if not DATABASE_URL:
        st.error("DATABASE_URL not found. Set it in .env locally, or in Streamlit Cloud's Secrets.")
        st.stop()
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def fetch_matches(min_score: int, location_filter: str, status_filter: str,
                   search_text: str, sort_by: str):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            query = """
                SELECT id, company, job_title, match_score, location_tag,
                       contact_name, posting_url, status, summary, created_at
                FROM job_matches
                WHERE match_score >= %s
            """
            params = [min_score]

            if location_filter != "All":
                query += " AND location_tag = %s"
                params.append(location_filter)

            if status_filter != "All":
                query += " AND status = %s"
                params.append(status_filter)

            if search_text:
                query += " AND (company ILIKE %s OR job_title ILIKE %s)"
                like_term = f"%{search_text}%"
                params.extend([like_term, like_term])

            if sort_by == "Newest first":
                query += " ORDER BY created_at DESC"
            else:
                query += " ORDER BY match_score DESC, created_at DESC"

            cur.execute(query, params)
            return cur.fetchall()
    finally:
        conn.close()


def fetch_status_counts():
    """Counts across ALL matches, ignoring current filters — for the summary bar."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT status, COUNT(*) as count
                FROM job_matches
                GROUP BY status;
            """)
            rows = cur.fetchall()
            counts = {"not_applied": 0, "applied": 0, "skipped": 0}
            for row in rows:
                counts[row["status"]] = row["count"]
            return counts
    finally:
        conn.close()


def update_status(match_id: int, new_status: str):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE job_matches SET status = %s WHERE id = %s;",
                (new_status, match_id),
            )
        conn.commit()
    finally:
        conn.close()


def clean_title(title: str) -> str:
    """Strip stray markdown bold markers the scoring agent sometimes leaves in titles."""
    return re.sub(r"\*\*", "", title).strip()


def score_class(score: int) -> str:
    if score >= 75:
        return "score-high"
    if score >= 60:
        return "score-mid"
    return "score-low"


# --- UI ---
st.title("Job Search Dashboard")

# Stats summary — reflects ALL matches regardless of current filters
counts = fetch_status_counts()
total = sum(counts.values())
stat1, stat2, stat3, stat4 = st.columns(4)
stat1.metric("Total", total)
stat2.metric("Applied", counts["applied"])
stat3.metric("Skipped", counts["skipped"])
stat4.metric("Pending", counts["not_applied"])

st.divider()

search_text = st.text_input("Search company or title", placeholder="e.g. agoda, financial analyst")

filter_row = st.columns(4)
with filter_row[0]:
    min_score = st.slider("Minimum match score", 0, 100, 65, step=5)
with filter_row[1]:
    location_filter = st.selectbox("Location", ["All", "preferred", "unclear", "excludes"])
with filter_row[2]:
    status_filter = st.selectbox("Status", ["All", "not_applied", "applied", "skipped"])
with filter_row[3]:
    sort_by = st.selectbox("Sort by", ["Score (high to low)", "Newest first"])

matches = fetch_matches(min_score, location_filter, status_filter, search_text, sort_by)
st.caption(f"{len(matches)} matches")

for m in matches:
    title = clean_title(m["job_title"])
    badge_class = score_class(m["match_score"])

    with st.container():
        st.markdown(f"""
        <div class="job-card">
            <div class="job-title">
                <span class="score-badge {badge_class}">{m['match_score']}</span>
                {m['company']} — {title}
            </div>
            <div class="job-meta">Location: {m['location_tag']} &nbsp;·&nbsp; Status: {m['status']}
                {f" &nbsp;·&nbsp; Contact: {m['contact_name']}" if m['contact_name'] else ""}
            </div>
            <div class="job-summary">{m['summary'] or ""}</div>
        </div>
        """, unsafe_allow_html=True)

        link_col, applied_col, skip_col, reset_col = st.columns([3, 1, 1, 1])
        with link_col:
            if m['posting_url']:
                st.markdown(f"[Open posting]({m['posting_url']})")
        with applied_col:
            if m['status'] != 'applied':
                if st.button("Mark applied", key=f"applied_{m['id']}"):
                    update_status(m['id'], 'applied')
                    st.rerun()
        with skip_col:
            if m['status'] != 'skipped':
                if st.button("Skip", key=f"skip_{m['id']}"):
                    update_status(m['id'], 'skipped')
                    st.rerun()
        with reset_col:
            if m['status'] != 'not_applied':
                if st.button("Reset", key=f"reset_{m['id']}"):
                    update_status(m['id'], 'not_applied')
                    st.rerun()
