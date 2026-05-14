"""Metis Insights Engine (M8) — scaffold only.

Hosts the face verification swap (DeepFace FaceNet, replacing
`services/api/app/modules/attendance/face_stub.py`) and risk-scoring
pipelines. Integrates with the core via Redis pub/sub and an HTTP API.
"""
