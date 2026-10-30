
from datetime import datetime, timezone

#from app.database import supabase
from app.database import get_supabase_client
from app.llm import generate_text
from app.research import search_public_web


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def run_competitor_research(
    company: str,
    competitors: list[str],
) -> dict:
    supabase = get_supabase_client()
    # Create a persistent job before doing the research.
    created = (
        supabase.table("jobs")
        .insert({
            "status": "processing",
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
    job_id = job["id"]

    try:
        subjects = [company] + competitors
        sources = []

        for subject in subjects:
            query = f"{subject} official website products pricing"
            try:
                found = search_public_web(query, max_results=4)
                for item in found:
                    item["subject"] = subject
                sources.extend(found)
            except Exception:
                # Continue if one search fails.
                continue

        if not sources:
            raise RuntimeError(
                "No public search results were returned. "
                "Try again later or use a different search term."
            )

        source_text = "\n\n".join(
            f"Subject: {s['subject']}\n"
            f"Title: {s['title']}\n"
            f"URL: {s['url']}\n"
            f"Snippet: {s['snippet']}"
            for s in sources
        )

        prompt = f"""
Create a concise competitor research report.

Main company or product: {company}
Competitors: {", ".join(competitors) or "None specified"}

Use only the supplied search snippets as evidence.
Do not invent facts, prices, features, or citations.
If information is missing or unclear, say so.
Distinguish sourced observations from your own analysis.
Include a comparison table covering:
- Product or service
- Target customers
- Main features
- Pricing (only if supported by evidence)
- Strengths
- Potential weaknesses or unknowns

Finish with key findings and recommended next research steps.
Include relevant source URLs next to the claims they support.

SEARCH RESULTS:
{source_text}
"""

        report = await generate_text(prompt)

        provider_summary = {}

        for source in sources:
            provider = source.get("provider", "unknown")
            provider_summary[provider] = (
                provider_summary.get(provider, 0) + 1
            )

        result = {
            "company": company,
            "competitors": competitors,
            "report": report,
            "sources": sources,
            "provider_summary": provider_summary,
        }

#        result = {
#            "company": company,
#            "competitors": competitors,
#            "report": report,
#            "sources": sources,
#        }

        (
            supabase.table("jobs")
            .update({
                "status": "completed",
                "result": result,
                "error_message": None,
                "completed_at": utc_now(),
                "updated_at": utc_now(),
            })
            .eq("id", job_id)
            .execute()
        )

        return {
            "job_id": job_id,
            "status": "completed",
            **result,
        }

    except Exception as exc:
        # Keep the error in the database for troubleshooting.
        (
            supabase.table("jobs")
            .update({
                "status": "failed",
                "error_message": str(exc)[:1000],
                "updated_at": utc_now(),
            })
            .eq("id", job_id)
            .execute()
        )
        raise
