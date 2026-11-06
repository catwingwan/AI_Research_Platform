
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

              
        # Search each company independently using multiple search categories.
        for subject in subjects:
            search_queries = [
                {
                    "query": f"{subject} official website products pricing",
                    "category": "official",
                },
                {
                    "query": f"{subject} software reviews independent review",
                    "category": "reviews",
                },
                {
                    "query": f"{subject} Reddit user experience discussions",
                    "category": "community",
                },
            ]

            try:
                candidate_sources = []
                seen_urls = set()

                # Collect results from all three search categories.
                for search_item in search_queries:
                    found = search_public_web(
                        search_item["query"],
                        max_results=MAX_SOURCES_PER_SUBJECT,
                        subject=subject,
                    )

                    for item in found:
                        url = item.get("url")

                        if not url:
                            continue

                        normalized_url = url.rstrip("/").lower()

                        if normalized_url in seen_urls:
                            continue

                        seen_urls.add(normalized_url)

                        item["subject"] = subject
                        candidate_sources.append(item)

                # Group results by their detected source type.
                source_groups = {
                    "official": [],
                    "review_platform": [],
                    "community": [],
                    "other": [],
                }

                for item in candidate_sources:
                    source_type = item.get("source_type", "other")

                    if source_type not in source_groups:
                        source_type = "other"

                    source_groups[source_type].append(item)

                # Select sources in a balanced order.
                # Available categories are preferred, but not forced.
                unique_sources = []

                category_order = [
                    "official",
                    "review_platform",
                    "community",
                    "other",
                ]

                while len(unique_sources) < MAX_SOURCES_PER_SUBJECT:
                    added_source = False

                    for category in category_order:
                        if source_groups[category]:
                            unique_sources.append(
                                source_groups[category].pop(0)
                            )
                            added_source = True

                            if len(unique_sources) >= MAX_SOURCES_PER_SUBJECT:
                                break

                    if not added_source:
                        break

                subject_count = len(unique_sources)

                # Record source coverage by company.
                source_coverage.append({
                    "subject": subject,
                    "source_count": subject_count,
                    "minimum_required": MIN_SOURCES_PER_SUBJECT,
                    "source_type_summary": {
                        source_type: sum(
                            1 for item in unique_sources
                            if item.get("source_type") == source_type
                        )
                        for source_type in category_order
                    },
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
        
You are a professional market research analyst.

Prepare a structured, evidence-based competitor research report.

RESEARCH SUBJECTS
Main company or product: {company}
Competitors: {", ".join(competitors) or "None specified"}

EVIDENCE RULES
1. Use only the supplied search results as factual evidence.
2. Do not invent company information, product features, prices,
   customer segments, market share, or business performance.
3. Do not create fake citations or URLs.
4. Attach source URLs to relevant factual claims.
5. If information is unavailable, write "Not found in supplied sources".
6. Clearly distinguish verified observations from analysis or inference.
7. Never interpret missing information as proof that a feature
   is unavailable.

8. In comparison tables, use these labels:
   - Yes: explicitly confirmed by supplied evidence.
   - No: explicitly stated as unavailable by a supplied source.
   - Partial: only some aspects are supported.
   - Not found in supplied sources: insufficient evidence.

9. Do not use "No" simply because a feature was not mentioned.

10. Distinguish free AI trials, included AI features, and paid AI
    add-ons. Do not describe them as equivalent.

11. Do not describe a product as "less suited", "weaker",
    "limited", or "lacking" unless the supplied evidence
    supports that conclusion.

12. Separate factual limitations from analytical observations.
    Label analytical observations as "Analysis" and explain
    which confirmed features support the conclusion.

13. Do not infer that a feature is unavailable merely because
    it is absent from a product's pricing page or search snippets.

14. When evidence is insufficient, use "Not found in supplied
    sources" instead of making a negative comparison.

REPORT STRUCTURE

## 1. Executive Summary
- Brief overview of the competitive landscape.
- Main differences between the companies.
- Most important findings.
- Important information gaps.

## 2. Company Overview
For each company, describe:
- Main products or services.
- Target customers, if supported by evidence.
- Business positioning.
- Key product characteristics.

## 3. Feature Comparison
Create a comparison table with these columns:
- Feature or capability
- {company}
- Each competitor
- Evidence / source URL

Only include features supported by the supplied sources.
Use "Not found in supplied sources" where information is unavailable.

## 4. Pricing Comparison
For each company, identify:
- Available pricing plans.
- Published prices and billing periods.
- Free plan or trial availability, if supported.

Do not estimate or assume prices.
If pricing information is unavailable, state that clearly.

## 5. Competitive Advantages and Limitations
For each company:
- Evidence-supported strengths.
- Potential weaknesses or limitations.
- Areas where information is insufficient.

Label analytical conclusions as "Analysis" rather than verified facts.

## 6. Strategic Opportunities for {company}
Identify:
- Potential areas for differentiation.
- Competitor capabilities worth studying.
- Possible product or service improvements.
- Questions that require further research.

Do not present recommendations as established facts.

## 7. Key Findings
Summarize the five most important findings.
Prioritize findings that are supported by multiple sources.

## 8. Research Confidence and Limitations
Explain:
- Which companies have sufficient source coverage.
- Which findings have direct supporting evidence.
- Which areas rely on limited information.
- What additional research would improve confidence.

## 9. Sources
List the supplied source URLs grouped by company.

QUALITY REQUIREMENTS
- Use clear, professional business language.
- Avoid generic marketing statements.
- Avoid repeating the same information in multiple sections.
- Make comparisons specific and useful for business decisions.
- Never fabricate evidence.

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
