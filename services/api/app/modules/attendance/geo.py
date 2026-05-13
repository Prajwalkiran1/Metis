"""Pure-Python haversine. Inputs are degrees, output is metres.

Accepts `Decimal` (from the DB) and `float` (from the request body)
transparently, since both go through float() internally.
"""
from __future__ import annotations

import math
from decimal import Decimal
from typing import Union

Number = Union[float, int, Decimal]

EARTH_RADIUS_M = 6_371_000.0


def haversine_m(lat1: Number, lon1: Number, lat2: Number, lon2: Number) -> float:
    """Great-circle distance in metres between two (lat, lon) points."""
    phi1 = math.radians(float(lat1))
    phi2 = math.radians(float(lat2))
    dphi = math.radians(float(lat2) - float(lat1))
    dlambda = math.radians(float(lon2) - float(lon1))
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return EARTH_RADIUS_M * c
