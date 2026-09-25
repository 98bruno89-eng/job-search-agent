Job Search Agent

An automated pipeline that sources job postings, scores them against my resume, and reviews its own output before saving results — built to run daily without me touching it.

Live dashboard: [add your Streamlit URL here]

What this does

Every weekday morning, this pipeline runs on its own and:

Pulls newly posted jobs from a set of companies' public job boards
Filters out postings that don't match my target roles or aren't US-based
Scores each remaining posting against my resume, producing a fit score along with specific matched skills, gaps, and a summary
Has a second AI step check that scoring for quality before it's saved — if the check fails, the scoring is redone
Saves everything to a database, viewable in a dashboard where I can review matches and mark ones I've applied to

The goal was to reduce the manual effort of searching multiple job boards daily, while keeping a human decision (mine) at the point that actually matters: deciding which jobs to apply to.

How it's built

The pipeline is organized into four stages, each with one responsibility:

Sourcing — pulls live postings from company career pages via their public APIs (Greenhouse, Lever) and Workday's internal API. Filters by job title and location before anything else happens.
Scoring — an LLM reads the resume and posting, and returns a structured assessment: fit score, matched qualifications, skill gaps, and specific resume suggestions.
Review — a second LLM call checks the scoring output against a fixed set of criteria (is it grounded in the actual resume and posting text, is it specific rather than generic, is it internally consistent). If it fails, the scoring step runs again with that feedback.
Dashboard — a Streamlit app for browsing results, filtering by score or location, and tracking application status.
Sourcing → Scoring → Review → Database → Dashboard

The pipeline runs automatically on a schedule via GitHub Actions. Data is stored in a Postgres database (Neon).

Why it's built this way

Two-step scoring and review, not one. A single LLM call scoring a resume against a job posting can produce output that sounds reasonable but isn't well grounded in the actual text. Adding a review step that checks the scoring against explicit criteria, and reruns it when it fails, catches a meaningful share of weak output before it reaches the database.

Model choice. The scoring and review steps use a smaller, cheaper model (GPT-4o-mini) rather than a larger one. An early run on the larger model used more tokens in one pass than the smaller model's entire daily free allowance — the cost difference was substantial enough to make the smaller model the clear choice, without a noticeable drop in output quality for this task.

Filtering before scoring, not after. Location and title filtering happen before a posting reaches the LLM, not after. This keeps token usage down and means irrelevant postings never take up review time.

Configurable target roles, not hardcoded. The title keywords, location preferences, and company list all live in one configuration section (src/sources.py), separate from the pipeline logic. It's currently set up for financial analyst and data analyst roles, but retargeting it to a different function or industry means editing that one file, not the underlying pipeline.

What's working and what isn't yet

Working: sourcing from Greenhouse and Lever, one working Workday integration, scoring, the review step, location filtering, the dashboard, and daily automation.

Limited: Workday coverage is currently one company. Each additional company requires manually finding that company's specific server configuration, since there's no public directory mapping companies to their Workday setup — this is real, incremental work rather than something that scales automatically.

Not built yet: selecting between multiple resume versions based on the posting, and an agent that proposes new companies to add rather than requiring manual research each time.

Running it locally

Requires Python 3.11+, a Postgres database, and an OpenAI API key.

pip install -r requirements.txt

Set the following in a .env file (never committed):

OPENAI_API_KEY=your_key
DATABASE_URL=your_postgres_connection_string

Run the pipeline:

python src/main.py

Run the dashboard:

cd dashboard
streamlit run app.py

Company sources are configured in src/sources.py.
