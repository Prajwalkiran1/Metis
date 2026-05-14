"""Learning Engine FastAPI entry point.

Scaffold only — `/health` reports the service is alive but disabled.
When M7 lands the consumers, knowledge graph, and tutor packages get
populated and `enabled` flips to true (driven by an env flag or
in-service health probe).
"""
from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="Metis Learning Engine", version="0.0.1")


@app.get("/health")
async def health() -> dict[str, object]:
    return {"status": "ok", "service": "learning-engine", "enabled": False}


@app.get("/")
async def root() -> dict[str, object]:
    return {"service": "learning-engine", "status": "scaffold-only"}
