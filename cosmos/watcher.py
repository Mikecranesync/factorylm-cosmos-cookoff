"""
Cosmos incident watcher — polls Matrix API for open incidents and analyzes them.

Routes analysis through CosmosAgent so that each incident receives tag history
context before being sent to Cosmos Reason 2.

Usage:
    python -m cosmos.watcher
    python cosmos/watcher.py
    python cosmos/watcher.py --matrix-url http://localhost:8000 --interval 5
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

# Ensure repo root is on sys.path when run as a script
try:
    from demo._paths import BASE_PATH
    _repo_root = str(BASE_PATH)
except ImportError:
    _repo_root = str(Path(__file__).resolve().parent.parent)
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

import httpx

from cosmos.agent import CosmosAgent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


async def run_watcher(matrix_url: str = "http://localhost:8000", interval: float = 5.0) -> None:
    """Poll Matrix API for open incidents and analyze them via CosmosAgent."""
    agent = CosmosAgent()
    agent.matrix_url = matrix_url  # override with CLI/env value
    seen: set[int] = set()

    logger.info("Cosmos watcher started — matrix=%s interval=%.0fs", matrix_url, interval)

    while True:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{matrix_url}/api/incidents",
                    params={"status": "open", "limit": 20},
                )
                resp.raise_for_status()
                incidents = resp.json()

                for inc in incidents:
                    inc_id = inc["id"]
                    if inc_id in seen:
                        continue
                    if inc.get("has_insight"):
                        seen.add(inc_id)
                        continue

                    logger.info("Analyzing incident #%d: %s", inc_id, inc.get("error_message", ""))

                    # Parse tags from incident
                    tags = {}
                    if inc.get("tags_json"):
                        try:
                            tags = json.loads(inc["tags_json"])
                        except (json.JSONDecodeError, TypeError):
                            pass

                    # Run analysis through agent (includes tag history fetch)
                    insight = await agent.on_incident(
                        incident_id=str(inc_id),
                        node_id=inc.get("node_id", "unknown"),
                        tags=tags,
                    )

                    # Post insight back to Matrix API
                    post_resp = await client.post(
                        f"{matrix_url}/api/insights",
                        json={
                            "incident_id": inc_id,
                            "summary": insight.summary,
                            "root_cause": insight.root_cause,
                            "confidence": insight.confidence,
                            "reasoning": insight.reasoning,
                            "suggested_checks": insight.suggested_checks,
                            "video_url": insight.video_url,
                            "cosmos_model": insight.cosmos_model,
                        },
                    )
                    post_resp.raise_for_status()

                    logger.info(
                        "✓ Insight stored for incident #%d — confidence=%.0f%% summary=%s",
                        inc_id, insight.confidence * 100, insight.summary[:80],
                    )
                    seen.add(inc_id)

        except httpx.ConnectError:
            logger.warning("Cannot reach Matrix API at %s — retrying in %.0fs", matrix_url, interval)
        except Exception:
            logger.exception("Watcher error")

        await asyncio.sleep(interval)


def main() -> None:
    parser = argparse.ArgumentParser(description="Cosmos incident watcher")
    parser.add_argument("--matrix-url", default=os.getenv("MATRIX_URL", "http://localhost:8000"))
    parser.add_argument("--interval", type=float, default=5.0)
    args = parser.parse_args()

    try:
        asyncio.run(run_watcher(matrix_url=args.matrix_url, interval=args.interval))
    except KeyboardInterrupt:
        logger.info("Watcher stopped.")


if __name__ == "__main__":
    main()
