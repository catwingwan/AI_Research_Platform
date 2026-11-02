
from datetime import datetime, timezone

from app.database import get_supabase_client
from app.llm import generate_text
from app.research import search_public_web


MIN_SOURCES_PER_SUBJECT = 2
MAX_SOURCES_PER_SUBJECT = 4


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
        source_coverage = []
        coverage_errors = []

        # Search each company independently.
        for subject in subjects:
            query = f"{subject} official website products pricing"

            try:
                found = search_public_web(
                    query,
                    max_results=MAX_SOURCES_PER_SUBJECT,
                )

                # Remove duplicate URLs for this subject.
                unique_sources = []
                seen_urls = set()

                for item in found:
                    url = item.get("url")

                    if not url:
                        continue

                    normalized_url = url.rstrip("/").lower()

                    if normalized_url in seen_urls:
                        continue

                    seen_urls.add(normalized_url)

                    item["subject"] = subject
                    unique_sources.append(item)

                subject_count = len(unique_sources)

                source_coverage.append({
                    "subject": subject,
                    "source_count": subject_count,
                    "minimum_required": MIN_SOURCES_PER_SUBJECT,
                    "status": (
                        "sufficient"
                        if subject_count >= MIN_SOURCES_PER_SUBJECT
                        else "insufficient"
                    ),
                })

                sources.extend(unique_sources)

                if subject_count < MIN_SOURCES_PER_SUBJECT:
                    coverage_errors.append(
                        f"{subject}: only {subject_count} relevant "
                        f"sources found; minimum is "
                        f"{MIN_SOURCES_PER_SUBJECT}"
                    )

            except Exception as exc:
                source_coverage.append({
                    "subject": subject,
                    "source_count": 0,
                    "minimum_required": MIN_SOURCES_PER_SUBJECT,
                    "status": "search_failed",
                })

                coverage_errors.append(
                    f"{subject}: search failed ({type(exc).__name__})"
                )

        # Do not generate a report with insufficient coverage.
        if coverage_errors:
            raise RuntimeError(
                "Insufficient competitor research coverage: "
                + "; ".join(coverage_errors)
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
            "source_coverage": source_coverage,
        }

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
