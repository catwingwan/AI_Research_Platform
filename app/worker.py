from datetime import datetime, timedelta, timezone
import asyncio
import logging
import time

from app.database import get_supabase_client
from app.competitor import run_competitor_research

logger = logging.getLogger(__name__)

POLL_INTERVAL = 5
STALE_JOB_MINUTES = 10
RECOVERY_INTERVAL = 60

def recover_stale_jobs():
    """Return abandoned processing jobs to the pending queue."""

    supabase = get_supabase_client()

    cutoff = (
        datetime.now(timezone.utc)
        - timedelta(minutes=STALE_JOB_MINUTES)
    ).isoformat()

    response = (
        supabase.table("jobs")
        .update({
            "status": "pending",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        .eq("status", "processing")
        .eq("request_type", "competitor_research")
        .lt("updated_at", cutoff)
        .select("id")
        .execute()
    )

    recovered = response.data or []

    if recovered:
        logger.warning(
            "Recovered %d stale research jobs",
            len(recovered),
        )

    return len(recovered)

async def process_pending_jobs():
    """Continuously process pending research jobs."""

    supabase = get_supabase_client()

    try:
        recover_stale_jobs()
    except Exception:
        logger.exception("Initial stale-job recovery failed")

    last_recovery = time.monotonic()

    while True:
        if time.monotonic() - last_recovery >= RECOVERY_INTERVAL:
            try:
                recover_stale_jobs()
            except Exception:
                logger.exception("Periodic stale-job recovery failed")

            last_recovery = time.monotonic()
        try:
            response = (
                supabase.table("jobs")
                .select("id, request_payload")
                .eq("status", "pending")
                .eq("request_type", "competitor_research")
                .order("created_at")
                .limit(1)
                .execute()
            )

            jobs = response.data or []

            logger.info(
                "Pending queue poll returned %d jobs",
                len(jobs),
            )

            if not jobs:
                await asyncio.sleep(POLL_INTERVAL)
                continue

            job = jobs[0]
            job_id = job["id"]
            payload = job["request_payload"]

            # Claim the job. This implementation assumes one worker
            # running in one Render service instance.

            claimed = (
                supabase.table("jobs")
                .update({
                    "status": "processing",
                    "updated_at": datetime.now(
                        timezone.utc
                    ).isoformat(),
                })
                .eq("id", job_id)
                .eq("status", "pending")
                .select("id")
                .execute()
            )

            if not claimed.data:
                await asyncio.sleep(1)
                continue

            logger.info("Starting research job: %s", job_id)

            await run_competitor_research(
                company=payload["company"],
                competitors=payload.get("competitors", []),
                job_id=job_id,
            )

            logger.info("Finished research job: %s", job_id)

        except asyncio.CancelledError:
            raise

        except Exception:
            logger.exception("Background worker encountered an error")
            await asyncio.sleep(POLL_INTERVAL)
