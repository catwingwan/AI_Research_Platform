import asyncio
import logging
from datetime import datetime, timezone

from app.database import get_supabase_client
from app.llm import generate_text
from app.research import clean_source_text, search_public_web

logger = logging.getLogger(__name__)

MIN_SOURCES_PER_SUBJECT = 2
MAX_SOURCES_PER_SUBJECT = 4

EVIDENCE_GAP_AREAS = {
    "pricing": [
        "pricing", "price", "per user", "per month",
        "per year", "billing", "subscription",
    ],
    "integrations": [
        "integration", "integrations", "integrate",
        "connected apps", "api",
    ],
    "mobile_support": [
        "mobile", "ios", "android", "app store", "mobile app",
    ],
    "ai_capabilities": [
        "artificial intelligence", " AI ",
        "AI features", "AI assistant", "AI agent",
    ],
}


def identify_evidence_gaps(
    subject_sources: list[dict],
) -> list[str]:
    """Identify research areas with insufficient keyword coverage."""

    evidence_text = " ".join(
        (
            source.get("title", "")
            + " "
            + source.get("snippet", "")
        )
        for source in subject_sources
    ).lower()

    gaps = []

    for area, keywords in EVIDENCE_GAP_AREAS.items():
        matched_keywords = sum(
            1
            for keyword in keywords
            if keyword.lower() in evidence_text
        )

        if matched_keywords < 2:
            gaps.append(area)

    return gaps


def recover_missing_evidence(
    subject: str,
    gaps: list[str],
    existing_urls: set[str] | None = None,
    job_id: str | None = None,
) -> list[dict]:
    """Search specifically for missing competitor evidence."""

    recovered_sources = []
    seen_urls = {
        url.rstrip("/").lower()
        for url in (existing_urls or set())
    }

    search_templates = {
        "pricing": f"{subject} official pricing plans costs",
        "integrations": f"{subject} official integrations API",
        "mobile_support": f"{subject} official mobile app iOS Android",
        "ai_capabilities": f"{subject} official AI features capabilities",
    }

    for gap in gaps:
        query = search_templates.get(gap)

        if not query:
            continue

        try:
            results = search_public_web(
                query,
                max_results=3,
                subject=subject,
            )
            if job_id:
                update_job_heartbeat(job_id)

            for item in results:
                if len(recovered_sources) >= 2:
                    break

                url = item.get("url")

                if not url:
                    continue

                normalized_url = url.rstrip("/").lower()

                if normalized_url in seen_urls:
                    continue

                seen_urls.add(normalized_url)

                item["title"] = clean_source_text(
                    item.get("title", "")
                )
                item["snippet"] = clean_source_text(
                    item.get("snippet", "")
                )
                item["subject"] = subject
                item["recovery_topic"] = gap

                recovered_sources.append(item)

                if len(recovered_sources) >= 2:
                    break

        except Exception as exc:
            logger.exception(
                "Evidence recovery failed | subject=%s | topic=%s | error=%s",
                subject,
                gap,
                str(exc),
            )

    return recovered_sources


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()

def update_job_heartbeat(job_id: str) -> None:
    """Refresh the job timestamp while research is running."""

    supabase = get_supabase_client()

    supabase.table("jobs").update({
        "updated_at": utc_now(),
    }).eq("id", job_id).eq("status", "processing").execute()

async def run_competitor_research(
    company: str,
    competitors: list[str],
    job_id: str,
) -> dict:
    supabase = get_supabase_client()

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
                    try:
                        found = await asyncio.to_thread(
                            search_public_web,
                            search_item["query"],
                            max_results=MAX_SOURCES_PER_SUBJECT,
                            subject=subject,
                        )

                        update_job_heartbeat(job_id)

                    except Exception as exc:
                        logger.exception(
                            "Search query failed | subject=%s | category=%s | error=%s",
                            subject,
                            search_item["category"],
                            str(exc),
                        )
                        continue

                    for result in found:
                        title = clean_source_text(result.get("title", ""))
                        snippet = clean_source_text(result.get("snippet", ""))

                        result["title"] = title
                        result["snippet"] = snippet

                        if any(marker in title + snippet for marker in ("Ã¢", "Ãƒ", "Ã‚", "Ã¯Â¿Â½")):
                            logger.warning(
                                "MOJIBAKE DETECTED AFTER SEARCH REPAIR | subject=%s | title=%r",
                                subject,
                                title,
                            )
                        else:
                            logger.info(
                                "SEARCH TEXT CLEAN AFTER REPAIR | subject=%s | title=%r",
                                subject,
                                title,
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

        # Recover evidence for missing research areas.
        for subject in subjects:
            subject_sources = [
                source for source in sources
                if source.get("subject") == subject
            ]

            gaps = identify_evidence_gaps(subject_sources)

            if not gaps:
                continue

            logger.info(
                "Evidence gaps identified | subject=%s | gaps=%s",
                subject,
                gaps,
            )

            recovered = await asyncio.to_thread(
                recover_missing_evidence,
                subject,
                gaps,
                existing_urls={
                    source.get("url", "").rstrip("/").lower()
                    for source in subject_sources
                    if source.get("url")
                },
                job_id=job_id,
            )

            update_job_heartbeat(job_id)

            existing_urls = {
                source.get("url", "").rstrip("/").lower()
                for source in subject_sources
            }

            added_count = 0

            for item in recovered:
                normalized_url = item.get("url", "").rstrip("/").lower()

                if normalized_url and normalized_url not in existing_urls:
                    sources.append(item)
                    existing_urls.add(normalized_url)
                    added_count += 1

            logger.info(
                "Evidence recovery completed | subject=%s | recovered=%d",
                subject,
                added_count,
            )

        # Refresh source coverage after recovery.
        coverage_errors = []

        for coverage in source_coverage:
            subject = coverage["subject"]

            subject_sources = [
                source for source in sources
                if source.get("subject") == subject
            ]

            source_count = len(subject_sources)

            coverage["source_count"] = source_count
            coverage["source_type_summary"] = {
                source_type: sum(
                    1 for item in subject_sources
                    if item.get("source_type") == source_type
                )
                for source_type in (
                    "official",
                    "review_platform",
                    "community",
                    "other",
                )
            }

            coverage["status"] = (
                "sufficient"
                if source_count >= MIN_SOURCES_PER_SUBJECT
                else "insufficient"
            )

            if source_count < MIN_SOURCES_PER_SUBJECT:
                coverage_errors.append(
                    f"{subject}: {source_count} sources found "
                    f"(minimum {MIN_SOURCES_PER_SUBJECT})"
                )

        # Generate the report only after final coverage validation.
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

COMPANY ATTRIBUTION RULES

A. Every supplied source has a Subject field identifying
   the company or product it relates to.

B. Use a source as direct evidence about a company only
   when its Subject matches that company.

C. Never attribute a feature, price, customer complaint,
   product limitation, or review of one company to another.

D. Do not transfer information between Notion, Asana,
   and Trello merely because they appear in the same report.

E. If a source compares multiple companies, use its
   comparison claims only when the supplied snippet
   explicitly supports those claims.

F. If a company's information is insufficient, state
   "Not found in supplied sources" rather than borrowing
   evidence from another company.

G. Before finalizing each company section, verify that
   every company-specific factual claim is supported
   by a source with the correct Subject.

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


15. CLASSIFY EVERY IMPORTANT FINDING by its evidence type:
    - Official fact: explicitly confirmed by the company's
      official website or documentation.
    - Professional review: an assessment by an independent
      publication or software review platform.
    - Customer feedback: an opinion or experience reported
      by an individual user or community.
    - Analysis: a conclusion drawn from multiple findings.

16. Never present professional reviews or individual customer
    opinions as objectively verified product facts.

17. When sources disagree, explicitly identify the conflict.
    Present both findings, identify their respective sources,
    and explain why the evidence may differ.

18. Do not resolve conflicting opinions by choosing one source
    without justification.

19. Distinguish isolated customer complaints from recurring
    customer sentiment. Do not describe an issue as widespread
    unless multiple independent sources support that conclusion.

20. Assign a research confidence level to each major finding:
    - High: directly supported by multiple reliable sources,
      preferably including an official source where applicable.
    - Medium: supported by one reliable source or several
      consistent secondary sources.
    - Low: based on limited evidence, individual opinions,
      conflicting sources, or uncertain information.

21. Confidence levels are qualitative assessments, not
    statistical measurements.

22. Flag outdated information when a publication date is
    available and relevant to the finding. Do not assume
    information is current merely because a URL is accessible.

23. Do not invent publication dates or claim that a source
    has been recently verified when its date is unavailable.

24. Separate current official pricing and feature information
    from older third-party reviews.

25. When comparing customer experience, describe the feedback
    as reported experience rather than a universal product
    characteristic.

26. Every major recommendation must identify the supporting
    evidence and explain any important uncertainty.

27. If two sources provide contradictory information, do not
    combine them into a single definitive conclusion.


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
ENCODING REQUIREMENTS
- Use standard ASCII hyphens (-) for compound words.
- Never output the character "Ã¢" or mojibake text.
- Use normal ASCII spaces around punctuation.
- Do not use unusual Unicode spacing characters.
- Preserve correct company names and product names.
- Avoid generic marketing statements.
- Avoid repeating the same information in multiple sections.
- Make comparisons specific and useful for business decisions.
- Never fabricate evidence.

SEARCH RESULTS:
{source_text}
"""

        report = await generate_text(prompt)
        report = clean_source_text(report)

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
