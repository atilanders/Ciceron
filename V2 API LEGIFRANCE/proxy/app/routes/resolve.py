from typing import Optional
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from app.services.resolver import (
    resolve_code_article,
    NotFoundError,
    AmbiguousError,
    TooBroadError,
)

router = APIRouter()


@router.get("/ping")
async def ping_resolve():
    return {"scope": "resolve", "status": "ok"}


@router.get("/code-article")
async def code_article(
    code: str = Query(..., description="Ex: Code du travail"),
    article: str = Query(..., description="Ex: L1221-1"),
    date: Optional[str] = Query(None, description="Ex: 2020-01-01 (YYYY-MM-DD)"),
):
    """
    Résout un article d'un code via:
    - POST /search (récupère LEGIARTI...)
    - POST /consult/getArticle (récupère contenu)
    """
    try:
        resolved = await resolve_code_article(code_hint=code, article_hint=article, date_hint=date)
        return {
            "ok": True,
            "legiarti_id": resolved.legiarti_id,
            "title": resolved.title,
            "article": resolved.article_num,
            "date_version": resolved.date_version,
            "raw": resolved.raw,  # pour debug, tu pourras ensuite renvoyer seulement le texte nettoyé
        }

    except TooBroadError as e:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": "TOO_BROAD", "message": str(e)},
        )

    except NotFoundError as e:
        return JSONResponse(
            status_code=404,
            content={"ok": False, "error": "NOT_FOUND", "message": str(e)},
        )

    except AmbiguousError as e:
        return JSONResponse(
            status_code=409,
            content={
                "ok": False,
                "error": "AMBIGUOUS",
                "message": str(e),
                "candidates": e.candidates,
            },
        )
