"""
title: Nuclear Safety Record Search
author: (your name)
description: Searches the independent Python + ChromaDB analysis engine for
    relevant nuclear safety records (inspection reports, Part 21 correspondence,
    etc.) and returns them to the model as retrieved context.
required_open_webui_version: 0.4.0
"""

import requests
from pydantic import BaseModel, Field


class Tools:
    class Valves(BaseModel):
        engine_url: str = Field(
            default="http://host.docker.internal:8010",
            description="Base URL of the independent analysis engine (analysis_engine.py). "
                        "Use host.docker.internal if Open WebUI is in Docker and the engine "
                        "runs on your host machine.",
        )
        top_k: int = Field(default=5, description="Number of results to retrieve per search.")

    def __init__(self):
        self.valves = self.Valves()

    async def search_safety_records(self, query: str) -> str:
        """
        Search the nuclear safety records analysis engine for documents relevant
        to the given query. Use this whenever the user asks about specific
        incidents, inspection findings, failure patterns, or wants records from
        the ADAMS-derived corpus rather than general knowledge.

        :param query: A natural-language description of what to search for,
            e.g. "reactor coolant pump failures at pressurized water reactors 2023".
        :return: A formatted list of matching records with accession numbers,
            titles, dates, and short snippets.
        """
        try:
            resp = requests.post(
                f"{self.valves.engine_url}/search",
                json={"query": query, "top_k": self.valves.top_k},
                timeout=30,
            )
            resp.raise_for_status()
            results = resp.json()
        except requests.RequestException as e:
            return f"Error contacting analysis engine at {self.valves.engine_url}: {e}"

        if not results:
            return "No matching records found in the analysis engine for this query."

        lines = [f"Found {len(results)} relevant record(s):\n"]
        for r in results:
            lines.append(
                f"- **{r.get('accession_number')}** ({r.get('document_date', 'n/a')}) "
                f"[{', '.join(r.get('document_type') or [])}]\n"
                f"  {r.get('title', 'Untitled')}\n"
                f"  Relevance score: {r.get('score', 0):.3f}\n"
                f"  Snippet: {r.get('snippet', '')[:300]}...\n"
            )
        return "\n".join(lines)
