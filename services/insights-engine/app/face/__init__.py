"""Face verification (M8a).

Empty. M8a ships `face_facenet.py` implementing the `verify_face`
signature that `services/api/app/modules/attendance/face_stub.py`
already exposes; the core API swaps its import at that point.

DPDP compliance contract: live frames are discarded after embedding
extraction; only `verification_confidence FLOAT` is persisted.
"""
