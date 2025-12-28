from fastapi import APIRouter

router = APIRouter()


@router.get("/ping")
async def ping_query():
    """
    Endpoint de test pour l'espace /query.
    Plus tard : POST /query pour les questions ouvertes.
    """
    return {"scope": "query", "status": "ok"}
