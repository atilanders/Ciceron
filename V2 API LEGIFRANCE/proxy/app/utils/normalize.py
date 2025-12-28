from __future__ import annotations

import re
from typing import Optional


def normalize_article_num(raw: Optional[str]) -> Optional[str]:
    """
    Normalise un numéro d'article pour le rendre plus 'search-friendly'.
    Exemples:
      'L 1221-1' -> 'L1221-1'
      '6 nonies' -> '6 nonies' (on garde les espaces utiles)
      '3-1' -> '3-1'
    """
    if not raw:
        return None

    s = raw.strip()

    # compactage des espaces inutiles autour des tirets
    s = re.sub(r"\s*-\s*", "-", s)

    # si commence par une lettre (L,R,D...) + espaces + chiffres -> colle la lettre
    s = re.sub(r"^([A-Za-z])\s+(\d)", r"\1\2", s)

    # réduit espaces multiples
    s = re.sub(r"\s+", " ", s)

    return s


def normalize_code_title(raw: Optional[str]) -> Optional[str]:
    """
    Normalise un nom de code (sans être trop agressif).
    """
    if not raw:
        return None
    s = raw.strip()
    s = re.sub(r"\s+", " ", s)
    return s
