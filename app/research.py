
import json
import logging
import os
import shutil
import subprocess

from ddgs import DDGS

logger = logging.getLogger(__name__)


def search_with_agent_reach(
    query: str,
    max_results: int = 5,
) -> list[dict]:
    """Search public web using Agent-Reach."""

    uv_path = shutil.which("uv")

    if not uv_path:
        raise RuntimeError("uv was not found on PATH")

    command = [
        uv_path,
        "tool",
        "run",
        "--from",
        "agent-reach",
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

        results.append({
            "title": item.get("title") or "",
            "url": url,
            "snippet": (item.get("text") or "")[:1200],
            "provider": "agent_reach",
        })

#        results.append({
#            "title": item.get("title") or "",
#            "url": url,
#            "snippet": (item.get("text") or "")[:1200],
#        })

    return results


def search_with_ddgs(
    query: str,
    max_results: int = 5,
) -> list[dict]:
    """Fallback search using DDGS."""

    results = []

    with DDGS() as search:
        for item in search.text(
            query,
            max_results=max_results
        ):
            url = item.get("href") or item.get("url")

            if not url:
                continue

            results.append({
                "title": item.get("title") or "",
                "url": url,
                "snippet": (item.get("body") or "")[:1200],
                "provider": "ddgs",
            })

#            results.append({
#                "title": item.get("title") or "",
#                "url": url,
#                "snippet": (item.get("body") or "")[:1200],
#            })

    return results


def search_public_web(
    query: str,
    max_results: int = 5,
) -> list[dict]:
    """Try Agent-Reach first, then fall back to DDGS."""

    use_agent_reach = (
        os.getenv("AGENT_REACH_ENABLED", "false").lower()
        in {"1", "true", "yes"}
    )

    if use_agent_reach:
        try:
            results = search_with_agent_reach(
                query,
                max_results
            )

            if results:
                logger.info(
                    "Agent-Reach returned %d results",
                    len(results)
                )
                return results

            logger.warning(
                "Agent-Reach returned no usable results"
            )

        except Exception as exc:
            logger.exception(
                "Agent-Reach search failed: %s",
                str(exc)
            )
            print("AGENT REACH ERROR:", repr(exc))


#        except Exception:
#            logger.exception(
#                "Agent-Reach search failed; trying DDGS"
#            ) 

    logger.info("Using DDGS web search")

    return search_with_ddgs(query, max_results)
