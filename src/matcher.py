"""
matcher.py — LLM-powered resume-to-job fit scoring (local version)

Adapted from the original Colab notebook:
- Reads resume PDF from a local file path instead of google.colab upload
- Loads OPENAI_API_KEY from .env instead of Colab env
"""

import os
import json
import pdfplumber
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def _clean_json_output(raw_output: str) -> str:
    """
    Strip markdown code fences (```json ... ``` or ``` ... ```) that models
    sometimes add even when told not to, so json.loads() doesn't choke on them.
    """
    text = raw_output.strip()
    if text.startswith("```"):
        # Remove opening fence (with optional "json" language tag) and closing fence
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    return text


def extract_resume_text(pdf_path: str) -> str:
    """Extract all text from a local resume PDF."""
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"Resume PDF not found at: {pdf_path}")

    resume_text = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                resume_text += page_text + "\n"

    if not resume_text.strip():
        raise ValueError("No text could be extracted — is this a scanned/image PDF?")

    return resume_text


def score_job_match(resume_text: str, job_posting: str) -> dict:
    """Send resume + job posting to GPT-4o, return parsed JSON fit assessment."""
    prompt = f"""You are an expert career coach and recruiter with deep knowledge of ATS (Applicant Tracking Systems) and hiring best practices.

Analyze how well this candidate's resume matches the provided job posting.
Return ONLY a valid JSON object with no extra text, no markdown, no code fences.

The JSON must have exactly these keys:
{{
  "match_score": <integer 0-100>,
  "summary": "<2-3 sentence overall assessment>",
  "matched_qualifications": ["<skill or qualification that matches>", ...],
  "skill_gaps": ["<missing skill or qualification>", ...],
  "ats_keywords_missing": ["<keyword from job posting not in resume>", ...],
  "resume_suggestions": [
    "<specific, actionable suggestion for improving the resume>",
    "<specific, actionable suggestion for improving the resume>",
    "<specific, actionable suggestion for improving the resume>"
  ],
  "recruiter_or_hiring_manager_name": "<a specific person's name ONLY if explicitly named in the posting text itself, e.g. 'Reporting to Jane Smith' or a named recruiter contact — otherwise null. Do NOT guess, infer, or invent a name.>",
  "job_location": "<the actual city/state/country location(s) stated in the posting, e.g. 'Miami, FL' or 'Bangkok, Thailand' — otherwise null if not stated>",
  "work_arrangement": "<one of: 'remote', 'hybrid', 'in-person', or 'unspecified' if the posting doesn't say>",
  "role_overview": "<2-3 plain-language sentences on what this role actually does day-to-day, based on the posting. Do NOT include company boilerplate, EEO statements, hashtag city lists, disclaimers, or generic 'about the company' marketing copy.>",
  "key_responsibilities": ["<a real, specific responsibility from the posting>", "... 3-6 items, concise, no boilerplate"],
  "key_requirements": ["<a real, specific requirement from the posting — this is about the ROLE's stated requirements in general, separate from the candidate-specific matched_qualifications/skill_gaps above>", "... 3-6 items, concise, no boilerplate"]
}}

RESUME:
{resume_text}

JOB POSTING:
{job_posting}
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        max_tokens=1500,
    )

    raw_output = response.choices[0].message.content.strip()
    cleaned = _clean_json_output(raw_output)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        raise ValueError(f"Model did not return valid JSON:\n{raw_output}")


SUPERVISOR_PROMPT = """You are a strict quality-control reviewer for an automated job-application pipeline.
Your job is NOT to redo the work — it's to catch bad output before a human sees it.

Review the following output against this rubric. Be skeptical by default.

RUBRIC:
1. FACTUAL GROUNDING — Does every claim in the output trace back to something
   actually present in the resume or job posting? Flag anything that looks invented
   or inferred beyond what's stated.
2. SPECIFICITY — Is this output specific to THIS resume and THIS job posting, or
   could it apply to almost any candidate/posting with the names swapped? Generic
   output fails this check.
3. INTERNAL CONSISTENCY — Do the match_score and the stated skill_gaps/matched_qualifications
   actually agree with each other? (e.g. a 90+ score with 5 major skill gaps listed is inconsistent.)
4. ACTIONABILITY — Are the suggestions concrete and specific, or vague advice
   ("improve your resume") that gives the candidate nothing to act on?

INPUT DATA:
Resume excerpt: {resume_text}
Job posting: {job_posting}
Agent output to review: {agent_output}

Return ONLY valid JSON, no markdown, no extra text:
{{
  "verdict": "approve" | "rerun",
  "failed_checks": ["<which rubric item(s) failed, if any>"],
  "feedback": "<specific instruction for what to fix, empty string if approved>",
  "confidence": <integer 0-100, how confident you are in this verdict>
}}
"""


def review_match(resume_text: str, job_posting: str, agent_output: dict) -> dict:
    """Supervisor check: review the scoring agent's output before it's saved."""
    prompt = SUPERVISOR_PROMPT.format(
        resume_text=resume_text[:3000],  # keep prompt size sane
        job_posting=job_posting,
        agent_output=json.dumps(agent_output),
    )

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        max_tokens=500,
    )

    raw_output = response.choices[0].message.content.strip()
    cleaned = _clean_json_output(raw_output)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        raise ValueError(f"Supervisor did not return valid JSON:\n{raw_output}")


def score_job_match_supervised(resume_text: str, job_posting: str, max_retries: int = 1) -> dict:
    """
    Score a job match, then have the supervisor agent review it.
    Reruns the scoring agent (with supervisor feedback appended) up to max_retries times
    if the supervisor flags it. Returns the final approved (or last-attempt) result,
    with supervisor metadata attached under "_supervisor".
    """
    feedback_note = ""
    attempt = 0

    while True:
        posting_input = job_posting if not feedback_note else (
            f"{job_posting}\n\n[Note for reviewer feedback from a prior attempt: {feedback_note}]"
        )
        result = score_job_match(resume_text, posting_input)
        review = review_match(resume_text, job_posting, result)

        attempt += 1
        if review["verdict"] == "approve" or attempt > max_retries:
            result["_supervisor"] = review
            return result

        print(f"  Supervisor flagged output (attempt {attempt}): {review['failed_checks']} — rerunning...")
        feedback_note = review["feedback"]


def score_multiple_postings(resume_text: str, postings: list[dict], supervised: bool = True) -> list[dict]:
    """
    Score a resume against multiple job postings.
    `postings` is a list of dicts: [{"company": ..., "job_title": ..., "text": ...}, ...]
    Returns the same list with a "result" key added, sorted by match_score descending.
    """
    scored = []
    for posting in postings:
        print(f"Scoring: {posting['company']} — {posting['job_title']}...")
        if supervised:
            result = score_job_match_supervised(resume_text, posting["text"])
        else:
            result = score_job_match(resume_text, posting["text"])
        scored.append({**posting, "result": result})

    scored.sort(key=lambda p: p["result"]["match_score"], reverse=True)
    return scored
