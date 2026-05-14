"""Metis Learning Engine (M7) — scaffold only.

This service is deployed but disabled. The core API never imports anything
from this package; all integration is via Redis pub/sub (event consumers
land in ``consumers/`` when M7 is built) and HTTP calls proxied through
``services/api/app/modules/ai_proxy``.
"""
