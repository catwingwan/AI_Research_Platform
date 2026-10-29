from functools import lru_cache
from supabase import Client, create_client
from app.config import settings

@lru_cache(maxsize=1)
def get_supabase_client() -> Client:
    if not settings.supabase_url or not settings.supabase_key:
        raise RuntimeError(
            "Supabase is not configured. Set SUPABASE_URL and "
            "SUPABASE_SERVICE_ROLE_KEY in the environment."
        )
    return create_client(settings.supabase_url, settings.supabase_key)

def check_database() -> dict:
    """Check connectivity by querying the jobs table created by the migration."""
    client = get_supabase_client()
    response = client.table("jobs").select("id").limit(1).execute()
    # A successful query is enough; the table may legitimately contain no rows.
    return {"connected": True}
