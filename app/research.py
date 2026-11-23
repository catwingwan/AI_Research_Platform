
import re
import json
import logging
import os
import shutil
import subprocess
from urllib.parse import urlparse

from ddgs import DDGS
from ftfy import fix_text

logger = logging.getLogger(__name__)


# Domains commonly used for software reviews.
REVIEW_DOMAINS = {
    "g2.com",
    "capterra.com",
    "trustradius.com",
    "getapp.com",
    "softwareadvice.com",
    "producthunt.com",
    "pcmag.com",
    "techradar.com",
    "zapier.com",
    "forbes.com",
    "tomsguide.com",
    "techrepublic.com",
    "businessinsider.com",
}

# Community and discussion platforms.
COMMUNITY_DOMAINS = {
    "reddit.com",
    "news.ycombinator.com",
    "stackoverflow.com",
    "quora.com",
}


def normalize_words(value: str) -> set[str]:
    """Convert text into normalized words."""
    return set(re.findall(r"[a-z0-9]+", value.lower()))


def is_relevant_result(
    subject: str,
    title: str,
    url: str,
    snippet: str,
) -> bool:
    """Check whether a search result mentions the actual subject."""

    subject_words = normalize_words(subject)

    if not subject_words:
        return True

    result_text = f"{title} {url} {snippet}"
    result_words = normalize_words(result_text)

    # Require all meaningful words in the subject name.
    return subject_words.issubset(result_words)


def classify_source(
    subject: str,
    url: str,
) -> str:
    """Classify a source conservatively."""

    hostname = (urlparse(url).hostname or "").lower()
    hostname = hostname.removeprefix("www.")

    # Recognize common review platforms and publications.
    if any(
        hostname == domain or hostname.endswith("." + domain)
        for domain in REVIEW_DOMAINS
    ):
        return "review_platform"

    # Recognize community and discussion websites.
    if any(
        hostname == domain or hostname.endswith("." + domain)
        for domain in COMMUNITY_DOMAINS
    ):
        return "community"

    # A company name is not necessarily its website domain.
    # Only classify as official when the hostname clearly matches
    # the subject's normalized name.
    subject_slug = re.sub(r"[^a-z0-9]", "", subject.lower())
    hostname_slug = re.sub(r"[^a-z0-9]", "", hostname.split(".")[0])

    if subject_slug and (
        subject_slug in hostname_slug
        or hostname_slug in subject_slug
    ):
        return "official"

    return "other"


def search_with_agent_reach(
    query: str,
    subject: str,
    max_results: int = 5,
) -> list[dict]:
    """Search public web using Agent-Reach."""

    uv_path = shutil.which("uv") or os.path.expanduser("~/.local/bin/uv")

    if not uv_path:
        raise RuntimeError("uv was not found on PATH")

    command = [
        uv_path,
        "tool",
        "run",
        "--from",
        "https://github.com/mamaruo/Agent-Reach/archive/refs/heads/fix/exa-api-key.zip",
        "agent-reach",
        "web",
        "search",
        query,
        "--limit",
        str(max_results),
    ]

    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
    )

    if completed.returncode != 0:
        logger.error("Agent-Reach return code: %s", completed.returncode)
        logger.error("Agent-Reach stdout: %s", completed.stdout[:2000])
        logger.error("Agent-Reach stderr: %s", completed.stderr[:2000])

        raise RuntimeError(
            f"Agent-Reach exited with code {completed.returncode}"
        )

    data = json.loads(completed.stdout)

    if not data.get("ok"):
        raise RuntimeError(
            f"Agent-Reach search failed: {data.get('error')}"
        )

    results = []

    for item in data.get("items", []):
        url = item.get("url")

        if not url:
            continue

        title = clean_source_text(item.get("title") or "")
        snippet = clean_source_text(item.get("text") or "")

        if not is_relevant_result(subject, title, url, snippet):
            continue

        results.append({
            "title": title,
            "url": url,
            "snippet": snippet[:1200],
            "provider": "agent_reach",
            "source_type": classify_source(subject, url),
        })

    return results


def search_with_ddgs(
    query: str,
    subject: str,
    max_results: int = 5,
) -> list[dict]:
    """Fallback search using DDGS."""

    results = []

    with DDGS() as search:
        for item in search.text(
            query,
            max_results=max_results,
        ):
            url = item.get("href") or item.get("url")

            if not url:
                continue

            title = clean_source_text(item.get("title") or "")
            snippet = clean_source_text(item.get("body") or "")

            if not is_relevant_result(subject, title, url, snippet):
                continue

            results.append({
                "title": title,
                "url": url,
                "snippet": snippet[:1200],
                "provider": "ddgs",
                "source_type": classify_source(subject, url),
            })

    return results


def search_public_web(
    query: str,
    max_results: int = 5,
    subject: str | None = None,
) -> list[dict]:
    """Try Agent-Reach first, then fall back to DDGS."""

    # Keep backward compatibility with existing callers.
    relevance_subject = subject or query

    use_agent_reach = (
        os.getenv("AGENT_REACH_ENABLED", "false").lower()
        in {"1", "true", "yes"}
    )

    if use_agent_reach:
        try:
            results = search_with_agent_reach(
                query,
                relevance_subject,
                max_results,
            )

            if results:
                logger.info(
                    "Agent-Reach returned %d results",
                    len(results),
                )
                return results

            logger.warning(
                "Agent-Reach returned no usable results"
            )

        except Exception as exc:
            logger.exception(
                "Agent-Reach search failed: %s",
                str(exc),
            )

    logger.info("Using DDGS web search")

    try:
        results = search_with_ddgs(
            query,
            relevance_subject,
            max_results,
        )

        logger.info(
            "DDGS returned %d results for query: %s",
            len(results),
            query,
        )

        return results

    except Exception as exc:
        logger.exception(
            "DDGS fallback search failed for query '%s': %s",
            query,
            str(exc),
        )
        raise


def clean_source_text(value: str) -> str:
    """Clean common text encoding problems in search results."""

    if not isinstance(value, str):
        return ""

    value = fix_text(value)

    # Repair known malformed punctuation sequences.
    replacements = {
        "\u00e2\u0080\u0094": " - ",
        "\u00e2\u0080\u0093": " - ",
        "\u00e2\u0080\u0098": "'",
        "\u00e2\u0080\u0099": "'",
        "\u00e2\u0080\u009c": '"',
        "\u00e2\u0080\u009d": '"',
        "\u00e2\u0089\u0088": "≈",
        "\u00e2\u0086\u0092": "→",
        "\u00c2\u00a9": "©",
        "\u2014": " - ",
        "\u2013": " - ",
        "â€˜": "'",
        "â€™": "'",
        "â€œ": '"',
        "â€�": '"',
        "â€“": "-",
        "â€”": "-",
        "â€¢": "-",
        "Â·": " - ",
        "â·": " - ",
        "·": " - ",
    }

    for corrupted, corrected in replacements.items():
        value = value.replace(corrupted, corrected)

    # Repair malformed separators with surrounding spaces and numeric ranges.
    value = value.replace("â ", " - ")
    value = re.sub(r"(?<=\d)â(?=\d)", "-", value)

    # Repair known missing-space separators from search snippets.
    known_separators = (
        "most",
        "all",
        "in",
        "tracking",
        "management",
        "together",
    )

    for word in known_separators:
        value = re.sub(
            rf"(?<=\w)â(?={word}\b)",
            " - ",
            value,
            flags=re.IGNORECASE,
        )

    # Normalize repeated spaces only.
    value = re.sub(r"[ \t]{2,}", " ", value).strip()

    return value
