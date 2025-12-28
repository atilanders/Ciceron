from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, List

from app.services.legifrance import lf_search, lf_get_article
from app.utils.dates import iso_date_to_millis
from app.utils.normalize import normalize_article_num, normalize_code_title


# =========================
# Erreurs "propres" resolver
# =========================

class ResolutionError(Exception):
    pass


class NotFoundError(ResolutionError):
    pass


class AmbiguousError(ResolutionError):
    """Plusieurs résultats possibles, besoin de précision."""
    def __init__(self, message: str, candidates: Optional[List[Dict[str, Any]]] = None):
        super().__init__(message)
        self.candidates = candidates or []


class TooBroadError(ResolutionError):
    pass


# =========================
# Modèle de retour standard
# =========================

@dataclass
class ResolvedArticle:
    source: str                    # ex: "CODE"
    legiarti_id: str               # ex: "LEGIARTI0000..."
    title: Optional[str]           # titre du texte/code si dispo
    article_num: Optional[str]     # ex: "L1221-1"
    date_version: Optional[str]    # ISO 'YYYY-MM-DD'
    raw: Dict[str, Any]            # réponse brute getArticle


# =========================
# Helpers payload /search
# =========================

def _search_payload_code_article(
    code_title: str,
    article_num: str,
    date_version: Optional[str],
) -> Dict[str, Any]:
    millis = iso_date_to_millis(date_version) if date_version else None

    filtres: List[Dict[str, Any]] = []
    if millis:
        filtres.append({"facette": "DATE_VERSION", "singleDate": millis})
    filtres.append({"facette": "TEXT_LEGAL_STATUS", "valeur": "VIGUEUR"})

    return {
        "fond": "CODE_ETAT",
        "recherche": {
            "champs": [
                # ⚠️ Important: pour les codes, TEXT_NOM_CODE est plus stable que TITLE
                {
                    "typeChamp": "TEXT_NOM_CODE",
                    "criteres": [{"typeRecherche": "EXACTE", "valeur": code_title, "operateur": "ET"}],
                    "operateur": "ET",
                },
                {
                    "typeChamp": "NUM_ARTICLE",
                    "criteres": [{"typeRecherche": "EXACTE", "valeur": article_num, "operateur": "ET"}],
                    "operateur": "ET",
                },
            ],
            "filtres": filtres,
            "pageNumber": 1,
            "pageSize": 10,
            "operateur": "ET",
            "sort": "PERTINENCE",
            # ⚠️ on évite ARTICLE en V1 (ça peut déclencher un 500 côté DILA)
            "typePagination": "DEFAUT",
        },
    }


def _extract_legiarti_id_from_search(search_resp: Dict[str, Any]) -> List[str]:
    """
    Récupère une liste d'ID LEGIARTI depuis la réponse /search.
    Selon les fonds/pagination, les champs peuvent varier; on essaie plusieurs chemins.
    """
    ids: List[str] = []
    results = search_resp.get("results") or []
    if not isinstance(results, list):
        return []

    for r in results:
        if not isinstance(r, dict):
            continue

        # Certains résultats contiennent des infos articles dans "articles"
        arts = r.get("articles") or []
        if isinstance(arts, list):
            for a in arts:
                if isinstance(a, dict):
                    _id = a.get("id")
                    if isinstance(_id, str) and _id.startswith("LEGIARTI"):
                        ids.append(_id)

        # Parfois l'id est directement dans un champ "id"
        _id2 = r.get("id")
        if isinstance(_id2, str) and _id2.startswith("LEGIARTI"):
            ids.append(_id2)

    # dédoublonne en conservant l'ordre
    seen = set()
    uniq: List[str] = []
    for x in ids:
        if x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq


def _fallback_payload_code_only(code_title: str) -> Dict[str, Any]:
    return {
        "fond": "CODE_ETAT",
        "recherche": {
            "champs": [
                {
                    "typeChamp": "TEXT_NOM_CODE",
                    "criteres": [{"typeRecherche": "EXACTE", "valeur": code_title, "operateur": "ET"}],
                    "operateur": "ET",
                },
            ],
            "filtres": [{"facette": "TEXT_LEGAL_STATUS", "valeur": "VIGUEUR"}],
            "pageNumber": 1,
            "pageSize": 5,
            "operateur": "ET",
            "sort": "PERTINENCE",
            "typePagination": "DEFAUT",
        },
    }


def _extract_title_from_article_resp(article_resp: Dict[str, Any]) -> Optional[str]:
    """
    Heuristiques: tente de trouver un titre long / title dans différents chemins.
    """
    if not isinstance(article_resp, dict):
        return None

    art = article_resp.get("article")
    if not isinstance(art, dict):
        art = article_resp  # parfois la structure est déjà "article-like"

    titles = art.get("textTitles") or art.get("titles") or []
    if isinstance(titles, list) and titles:
        first = titles[0]
        if isinstance(first, dict):
            return first.get("title") or first.get("titreLong")

    return None


# =========================
# Résolveurs métier (V1)
# =========================

async def resolve_code_article(
    code_hint: str,
    article_hint: str,
    date_hint: Optional[str] = None,
) -> ResolvedArticle:
    """
    Résout un article d'un code:
      1) POST /search -> récupérer LEGIARTI...
      2) POST /getArticle -> récupérer contenu
    """
    code_title = normalize_code_title(code_hint)
    article_num = normalize_article_num(article_hint)

    if not code_title or not article_num:
        raise TooBroadError("code_hint ou article_hint manquant")

    payload = _search_payload_code_article(code_title, article_num, date_hint)

    try:
        search_resp = await lf_search(payload)
    except Exception:
        # Fallback : élargit la recherche, au cas où NUM_ARTICLE exact + date déclenche un bug
        search_resp = await lf_search(_fallback_payload_code_only(code_title))

    ids = _extract_legiarti_id_from_search(search_resp)

    if not ids:
        raise NotFoundError(
            f"Aucun article trouvé pour '{code_title}' article '{article_num}' (date={date_hint})."
        )

    # Si plusieurs IDs, on garde le 1er mais on signale ambiguïté si trop
    if len(ids) > 3:
        raise AmbiguousError(
            f"Plusieurs articles possibles ({len(ids)}). Précise le code exact ou l'intitulé.",
            candidates=[{"id": _id} for _id in ids[:10]],
        )

    legiarti_id = ids[0]
    article_resp = await lf_get_article(legiarti_id)

    title = _extract_title_from_article_resp(article_resp)

    return ResolvedArticle(
        source="CODE",
        legiarti_id=legiarti_id,
        title=title,
        article_num=article_num,
        date_version=date_hint,
        raw=article_resp,
    )


# =========================
# Dispatcher depuis JSON Make
# =========================

async def dispatch_from_make_json(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    payload = JSON issu de Make (après parse JSON), ex:
    {
      "intent": "LEGAL",
      "route_target": "RESOLVE",
      "topic": "...",
      "code_hint": "Code du travail",
      "article_hint": "L1221-1",
      "text_number": null,
      "date_hint": "2020-01-01",
      "missing_info": []
    }
    """
    intent = payload.get("intent")
    route_target = payload.get("route_target")

    if intent == "NOT_LEGAL":
        return {"ok": False, "error": "NOT_LEGAL", "message": "Question non juridique."}

    if intent == "TOO_VAGUE":
        return {
            "ok": False,
            "error": "TOO_VAGUE",
            "message": "Question trop vague. Précise les éléments manquants.",
            "missing_info": payload.get("missing_info") or [],
        }

    if route_target != "RESOLVE":
        return {
            "ok": False,
            "error": "WRONG_ROUTE",
            "message": "Ce dispatcher RESOLVE a reçu une requête non RESOLVE.",
        }

    code_hint = payload.get("code_hint")
    article_hint = payload.get("article_hint")
    date_hint = payload.get("date_hint")

    if code_hint and article_hint:
        resolved = await resolve_code_article(
            code_hint=code_hint,
            article_hint=article_hint,
            date_hint=date_hint,
        )
        return {
            "ok": True,
            "kind": "article",
            "source": resolved.source,
            "legiarti_id": resolved.legiarti_id,
            "title": resolved.title,
            "article": resolved.article_num,
            "date_version": resolved.date_version,
            "raw": resolved.raw,
        }

    # on ajoutera ici les autres scénarios : constitution, loi numérotée, date signature, etc.
    return {
        "ok": False,
        "error": "NOT_IMPLEMENTED",
        "message": "RESOLVE non implémenté pour ce type de demande (besoin code+article ou autre scénario).",
    }
