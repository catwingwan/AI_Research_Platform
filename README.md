# AI Research Platform — Phase 1

Minimal FastAPI service for Render with a Supabase connectivity check.

## What is included

- `GET /` — service information
- `GET /health` — liveness endpoint (does not depend on Supabase)
- `GET /health/ready` — checks Supabase connectivity by querying `public.jobs`
- `migrations/001_initial_schema.sql` — initial database table
- `render.yaml` — Render Blueprint configuration

## 1. Create Supabase project

1. Create a project at https://supabase.com/.
2. Open **SQL Editor** and run `migrations/001_initial_schema.sql`.
3. Open **Project Settings → API** (or the API keys page in the current dashboard).
4. Copy the Project URL and the **service_role/secret key** for backend use only.

Never put the service-role key in frontend JavaScript, commit it to Git, or share it publicly.

## 2. Run locally (optional)

Python 3.11 or 3.12 is recommended.

### Windows PowerShell

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` with your Supabase project URL and service-role key, then run:

```powershell
$env:APP_NAME = "AI Research Platform"
$env:ENVIRONMENT = "development"
$env:SUPABASE_URL = "https://YOUR-PROJECT-REF.supabase.co"
$env:SUPABASE_SERVICE_ROLE_KEY = "YOUR_SECRET_KEY"
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/docs`, then test `/health` and `/health/ready`.

## 3. Push to GitHub

Create an empty repository on GitHub, then from this project folder:

```powershell
git init
git add .
git commit -m "Phase 1: FastAPI and Supabase foundation"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/YOUR-REPOSITORY.git
git push -u origin main
```

Do not commit `.env` or any real secret.

## 4. Deploy to Render

1. In Render, choose **New → Blueprint** and connect the GitHub repository.
2. Render reads `render.yaml` and creates the web service.
3. Add `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` as secret environment variables when prompted.
4. Deploy and open the service URL.

Test:
- `/health` should return `{"status":"ok","environment":"production"}`
- `/health/ready` should return `{"status":"ready","database":"connected"}`

Render's free web service may sleep after inactivity. The health endpoint does not keep it awake.

## Troubleshooting

- `503` from `/health/ready`: verify the URL/key, confirm the SQL migration ran, and inspect Render logs.
- `ModuleNotFoundError`: verify the build command installed `requirements.txt`.
- Never return the full exception or secret values in public API responses.

## Phase 1 scope boundary

This scaffold does not yet accept public research jobs, run Agent-Reach, call an LLM, or expose customer data. Those are later phases. Keep the database private until authentication and row-level security policies are designed.
