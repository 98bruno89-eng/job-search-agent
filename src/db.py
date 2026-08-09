"""
db.py — Postgres (Neon) connection + table setup for job-search-agent
"""

import os
import psycopg2
from psycopg2.extras import RealDictCursor, Json
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")


def get_connection():
    """Return a new psycopg2 connection using the .env DATABASE_URL."""
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL not found — check your .env file")
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def init_db():
    """Create the job_matches table if it doesn't exist yet."""
    ddl = """
    CREATE TABLE IF NOT EXISTS job_matches (
        id SERIAL PRIMARY KEY,
        company TEXT,
        job_title TEXT,
        job_posting_text TEXT,
        source TEXT,
        external_id TEXT,
        posting_url TEXT,
        location_tag TEXT,
        contact_name TEXT,
        job_location TEXT,
        work_arrangement TEXT,
        role_overview TEXT,
        key_responsibilities JSONB,
        key_requirements JSONB,
        match_score INTEGER,
        summary TEXT,
        matched_qualifications JSONB,
        skill_gaps JSONB,
        ats_keywords_missing JSONB,
        resume_suggestions JSONB,
        supervisor_verdict TEXT,
        supervisor_confidence INTEGER,
        supervisor_feedback TEXT,
        status TEXT DEFAULT 'not_applied',
        created_at TIMESTAMP DEFAULT NOW()
    );
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(ddl)
        conn.commit()
        print("job_matches table ready.")
    finally:
        conn.close()


def save_match(company, job_title, job_posting_text, result: dict,
               source: str = None, external_id: str = None, posting_url: str = None,
               location_tag: str = None):
    """Insert one scored job match into the database. `result` is the parsed JSON from matcher.py."""
    supervisor = result.get("_supervisor", {})

    sql = """
    INSERT INTO job_matches
        (company, job_title, job_posting_text, source, external_id, posting_url, location_tag,
         contact_name, job_location, work_arrangement, role_overview,
         key_responsibilities, key_requirements, match_score, summary,
         matched_qualifications, skill_gaps, ats_keywords_missing, resume_suggestions,
         supervisor_verdict, supervisor_confidence, supervisor_feedback)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    RETURNING id;
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (
                company,
                job_title,
                job_posting_text,
                source,
                external_id,
                posting_url,
                location_tag,
                result.get("recruiter_or_hiring_manager_name"),
                result.get("job_location"),
                result.get("work_arrangement"),
                result.get("role_overview"),
                Json(result.get("key_responsibilities", [])),
                Json(result.get("key_requirements", [])),
                result.get("match_score"),
                result.get("summary"),
                Json(result.get("matched_qualifications", [])),
                Json(result.get("skill_gaps", [])),
                Json(result.get("ats_keywords_missing", [])),
                Json(result.get("resume_suggestions", [])),
                supervisor.get("verdict"),
                supervisor.get("confidence"),
                supervisor.get("feedback"),
            ))
            new_id = cur.fetchone()["id"]
        conn.commit()
        return new_id
    finally:
        conn.close()


def get_scored_keys() -> set[str]:
    """Return a set of 'source:external_id' strings for postings already scored — used for dedup."""
    sql = "SELECT source, external_id FROM job_matches WHERE source IS NOT NULL AND external_id IS NOT NULL;"
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
            return {f"{row['source']}:{row['external_id']}" for row in rows}
    finally:
        conn.close()


def get_top_matches(limit=10, min_score=None):
    """Return the top-scoring matches, highest first. Optionally filter by a minimum score."""
    if min_score is not None:
        sql = """
        SELECT id, company, job_title, match_score, status, posting_url, location_tag, contact_name, created_at
        FROM job_matches
        WHERE match_score >= %s
        ORDER BY match_score DESC
        LIMIT %s;
        """
        params = (min_score, limit)
    else:
        sql = """
        SELECT id, company, job_title, match_score, status, posting_url, location_tag, contact_name, created_at
        FROM job_matches
        ORDER BY match_score DESC
        LIMIT %s;
        """
        params = (limit,)

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    finally:
        conn.close()
