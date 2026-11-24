import asyncio
import logging
from contextlib import asynccontextmanager

from app.worker import process_pending_jobs

from fastapi import FastAPI, HTTPException
from app.config import settings
from app.database import check_database

import httpx
from pydantic import BaseModel, Field
#from fastapi import HTTPException
from app.llm import generate_text

@asynccontextmanager
async def lifespan(app: FastAPI):
    worker_task = asyncio.create_task(
        process_pending_jobs()
    )

    logging.info("Background research worker started")

    yield

    worker_task.cancel()

    try:
        await worker_task
    except asyncio.CancelledError:
        logging.info("Background research worker stopped")


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Cloud-hosted AI research service API.",
    lifespan=lifespan,
)

class LLMTestRequest(BaseModel):
    prompt: str = Field(min_length=3, max_length=2000)

class CompetitorResearchRequest(BaseModel):
    company: str = Field(min_length=2, max_length=150)
    competitors: list[str] = Field(default_factory=list, max_length=5)



@app.post("/api/llm/test")
async def test_llm(request: LLMTestRequest):
    try:
        result = await generate_text(request.prompt)
        return {
            "status": "success",
            "model": "openrouter/free",
            "result": result,
        }
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=(
                f"LLM provider returned HTTP "
                f"{exc.response.status_code}"
            ),
        ) from exc
    except (httpx.RequestError, RuntimeError) as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc),
        ) from exc


@app.post("/api/research/competitors", status_code=202)
async def competitor_research(request: CompetitorResearchRequest):
    try:
        company = request.company.strip()
        competitors = [
            name.strip()
            for name in request.competitors
            if name.strip()
        ]

        if not company:
            raise HTTPException(
                status_code=422,
                detail="Company name cannot be empty",
            )

        if company.lower() in {c.lower() for c in competitors}:
            raise HTTPException(
                status_code=422,
                detail="The company should not also be a competitor",
            )

        from app.database import get_supabase_client

        supabase = get_supabase_client()

        created = (
            supabase.table("jobs")
            .insert({
                "status": "pending",
                "request_type": "competitor_research",
                "request_payload": {
                    "company": company,
                    "competitors": competitors,
                },
            })
            .execute()
        )

        if not created.data:
            raise RuntimeError("Could not create research job")

        job = created.data[0]

        return {
            "job_id": job["id"],
            "status": "pending",
            "message": "Research job queued successfully",
        }

    except HTTPException:
        raise
    except Exception as exc:
        import logging
        logging.exception("Could not queue competitor research")
        raise HTTPException(
            status_code=502,
            detail="Could not queue research job",
        ) from exc

@app.get("/api/jobs/{job_id}")
async def get_job_status(job_id: str):
    try:
        from app.database import get_supabase_client

        supabase = get_supabase_client()

        response = (
            supabase.table("jobs")
            .select(
                "id, status, result, error_message, "
                "created_at, updated_at, completed_at"
            )
            .eq("id", job_id)
            .limit(1)
            .execute()
        )

        jobs = response.data or []

        if not jobs:
            raise HTTPException(
                status_code=404,
                detail="Research job not found",
            )

        return jobs[0]

    except HTTPException:
        raise
    except Exception as exc:
        logging.exception("Could not retrieve research job")
        raise HTTPException(
            status_code=502,
            detail="Could not retrieve research job",
        ) from exc

@app.get("/")
def root():
    return {
        "name": settings.app_name,
        "status": "running",
        "docs": "/docs",
        "health": "/health",
        "readiness": "/health/ready",
    }

@app.get("/health")
def health():
    # Liveness only: this endpoint should work even if Supabase is unavailable.
    return {"status": "ok", "environment": settings.environment}

@app.get("/health/ready")
def readiness():
    # Readiness checks that required configuration and database access work.
    try:
        check_database()
        return {"status": "ready", "database": "connected"}
    except Exception as exc:
        # Do not expose credentials or internal exception details to callers.
        raise HTTPException(
            status_code=503,
            detail="Database is not ready. Check server configuration and logs.",
        ) from exc
