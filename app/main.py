from fastapi import FastAPI, HTTPException
from app.config import settings
from app.database import check_database

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Cloud-hosted AI research service API.",
)

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
