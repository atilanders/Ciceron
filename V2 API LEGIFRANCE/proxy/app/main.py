from fastapi import FastAPI

from app.routes.resolve import router as resolve_router
from app.routes.query import router as query_router


def create_app() -> FastAPI:
    """
    Fabrique l'application FastAPI et branche les routes principales.
    Ici : aucune logique Légifrance, uniquement de l'architecture.
    """
    app = FastAPI(
        title="Proxy Légifrance v2",
        version="0.1.0",
        description="Proxy HTTP pour interroger l'API Légifrance au service de ton IA juridique.",
    )

    # Routes pour les résolutions précises (code + article, lois numérotées, etc.)
    app.include_router(resolve_router, prefix="/resolve", tags=["resolve"])

    # Routes pour les questions ouvertes / RAG
    app.include_router(query_router, prefix="/query", tags=["query"])

    # Petit endpoint de santé pour vérifier que le proxy tourne
    @app.get("/health", tags=["health"])
    async def health():
        return {"status": "ok"}

    return app


# Instance globale utilisée par uvicorn
app = create_app()
