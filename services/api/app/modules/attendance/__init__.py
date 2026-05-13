"""M3 — Attendance Service.

Materialises `class_sessions` from M2's timetable, mints signed-JWT QR
tokens that rotate every 90s, validates submits via three independent
anti-proxy layers (QR signature/jti, GPS haversine, face-match stub),
and exposes a state machine for teacher review.
"""
