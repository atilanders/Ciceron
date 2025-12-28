from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional


def iso_date_to_millis(date_str: Optional[str]) -> Optional[int]:
    """
    Convertit une date ISO 'YYYY-MM-DD' en timestamp millisecondes UTC.
    Si date_str est None -> None.
    """
    if not date_str:
        return None

    # On accepte aussi 'YYYY/MM/DD' par tolérance légère
    s = date_str.strip().replace("/", "-")

    # format strict
    dt = datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)
