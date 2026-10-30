from fastapi import FastAPI, HTTPException
from app.config import settings
from app.database import check_database

import httpx
from pydantic import BaseModel, Field
#from fastapi import HTTPException
from app.llm import generate_text
from app.competitor import run_competitor_research

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Cloud-hosted AI research service API.",
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
    

@app.post("/api/research/competitors")
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

        return await run_competitor_research(
            company=company,
            competitors=competitors,
        )

    except HTTPException:
        raise
    except Exception as exc:
        import logging

        logging.exception("Competitor research failed")
        raise HTTPException(
            status_code=502,
            detail=f"Research failed: {type(exc).__name__}: {exc}",
        ) from exc
  
'''   except Exception:
        raise HTTPException(
            status_code=502,
            detail=(
                "Research failed. Check the application terminal "
                "and the Supabase jobs table for details."
            ),
        )
'''    

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
