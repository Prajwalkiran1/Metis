"""Insights Engine FastAPI entry point.

Scaffold only — `/health` reports the service is alive but disabled.
M8a wires the face verification swap; M8b/c populate risk-scoring,
class insights, and anomaly detection.
"""
from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="Metis Insights Engine", version="0.0.1")


@app.get("/health")
async def health() -> dict[str, object]:
    return {"status": "ok", "service": "insights-engine", "enabled": False}


@app.get("/")
async def root() -> dict[str, object]:
    return {"service": "insights-engine", "status": "scaffold-only"}
