# Job Search Dashboard

A small Streamlit app to browse scored job matches and mark them as applied —
built to be accessible from any device, including your phone, once deployed.

## Run it locally first (to test)

```
cd dashboard
pip install -r requirements.txt
streamlit run app.py
```

It'll open in your browser at `http://localhost:8501`, reading from the same
`DATABASE_URL` in your project's `.env` file (make sure `dashboard/` has
access to it — either copy `.env` into `dashboard/`, or run streamlit from
the project root with `streamlit run dashboard/app.py`).

## Deploy for free, phone-accessible (Streamlit Community Cloud)

1. Go to https://share.streamlit.io and sign in with your GitHub account
2. Click "New app"
3. Select your `job-search-agent` repository, branch `main`
4. Set "Main file path" to `dashboard/app.py`
5. Before deploying, click "Advanced settings" → "Secrets" and add:
   ```
   DATABASE_URL = "your_real_neon_connection_string_here"
   ```
   (This is separate from GitHub Secrets — Streamlit Cloud has its own
   secrets manager, and needs this value entered there directly.)
6. Click "Deploy"

Once deployed, you'll get a public URL like
`https://job-search-agent-yourname.streamlit.app` — open that from your
phone, bookmark it, and you have a live, always-on dashboard.

**Note:** since this becomes a public URL, anyone with the link could
technically view your job search matches (though they'd need your database
credentials to change anything beyond what the app's own buttons allow).
If that's a concern, Streamlit Community Cloud also supports app-level
password protection under app settings — worth enabling if you don't want
this link open to anyone who finds it.
