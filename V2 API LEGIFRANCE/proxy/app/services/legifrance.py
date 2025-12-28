import asyncio
import time
from typing import Any, Dict, Optional

import httpx

from app.config import (
    PISTE_CLIENT_ID,
    PISTE_CLIENT_SECRET,
    PISTE_TOKEN_URL,
    LEGIFRANCE_API_BASE,
    REQUEST_TIMEOUT,
)

# ================================
# Cache simple du token en mémoire
# ================================

_access_token: Optional[str] = None
_token_expires_at: Optional[float] = None  # timestamp en secondes
_token_lock = asyncio.Lock()

# ================================
# Client HTTP réutilisable (perf)
# ================================

_client: Optional[httpx.AsyncClient] = None


def _get_client() -> httpx.AsyncClient:
    """
    Retourne un client httpx partagé (créé à la demande).
    """
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=REQUEST_TIMEOUT)
    return _client


async def aclose_client() -> None:
    """
    À appeler au shutdown de l'app pour fermer proprement les connexions.
    """
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


class LegifranceAuthError(Exception):
    """Erreur d'authentification PISTE / Légifrance."""


class LegifranceApiError(Exception):
    """Erreur d'appel à l'API Légifrance."""


async def _fetch_new_token() -> str:
    """
    Récupère un nouveau token OAuth2 auprès de PISTE.
    Met à jour le cache global _access_token et _token_expires_at.
    """
    global _access_token, _token_expires_at

    if not PISTE_CLIENT_ID or not PISTE_CLIENT_SECRET:
        raise LegifranceAuthError("PISTE_CLIENT_ID / PISTE_CLIENT_SECRET manquants.")

    data = {
        "grant_type": "client_credentials",
        "client_id": PISTE_CLIENT_ID,
        "client_secret": PISTE_CLIENT_SECRET,
        "scope": "openid",
    }

    client = _get_client()
    resp = await client.post(PISTE_TOKEN_URL, data=data)

    if resp.status_code != 200:
        raise LegifranceAuthError(
            f"Échec token PISTE (status={resp.status_code}, body={resp.text})"
        )

    payload = resp.json()
    token = payload.get("access_token")
    if not token:
        raise LegifranceAuthError("Réponse PISTE sans access_token.")

    # ✅ cast int pour éviter bugs si expires_in arrive en string
    expires_in = int(payload.get("expires_in", 3600))

    # marge de sécurité 60s
    _access_token = token
    _token_expires_at = time.time() + expires_in - 60

    return token


async def get_token() -> str:
    """
    Retourne un token valide, en rafraîchissant si nécessaire.
    (Protégé par lock pour éviter plusieurs refresh simultanés)
    """
    global _access_token, _token_expires_at

    now = time.time()
    if _access_token and _token_expires_at and now < _token_expires_at:
        return _access_token

    async with _token_lock:
        now2 = time.time()
        if _access_token and _token_expires_at and now2 < _token_expires_at:
            return _access_token
        return await _fetch_new_token()


def _invalidate_token_cache() -> None:
    """
    Invalide le cache token (utile si 401 côté Légifrance).
    """
    global _access_token, _token_expires_at
    _access_token = None
    _token_expires_at = None


def _ensure_consult_base(base: str) -> str:
    """
    L'API Légifrance est généralement consommée via .../lf-engine-app/consult/*
    Si l'env oublie /consult, on le rajoute.
    """
    b = (base or "").rstrip("/")
    if not b:
        raise LegifranceApiError("LEGIFRANCE_API_BASE est vide.")
    if not b.endswith("/consult"):
        b = f"{b}/consult"
    return b


async def _post_legifrance(endpoint: str, json_payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Appel POST générique vers l'API Légifrance (partie /consult).
    Gère automatiquement:
      - Bearer token
      - retries (429/5xx + erreurs réseau)
      - refresh token automatique si 401
    """
    base = _ensure_consult_base(LEGIFRANCE_API_BASE)
    url = f"{base}/{endpoint.lstrip('/')}"
    client = _get_client()

    async def _do_post() -> httpx.Response:
        token = await get_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",  # ✅ recommandé
        }
        return await client.post(url, headers=headers, json=json_payload)

    last_exc: Optional[Exception] = None
    resp: Optional[httpx.Response] = None
    refreshed_after_401 = False

    for attempt in range(3):
        try:
            resp = await _do_post()

            # ✅ Si 401, on force un refresh token une seule fois
            if resp.status_code == 401 and not refreshed_after_401:
                _invalidate_token_cache()
                refreshed_after_401 = True
                resp = await _do_post()

            # retries utiles
            if resp.status_code in (429, 500, 502, 503, 504):
                await asyncio.sleep(0.2 * (2 ** attempt))
                continue

            break

        except (httpx.TimeoutException, httpx.NetworkError) as e:
            last_exc = e
            await asyncio.sleep(0.2 * (2 ** attempt))

    else:
        raise LegifranceApiError(f"Échec réseau Légifrance après retries: {last_exc}")

    if resp is None:
        raise LegifranceApiError("Aucune réponse reçue de Légifrance.")

    if resp.status_code >= 400:
        raise LegifranceApiError(
            f"Appel Légifrance {endpoint} en erreur (status={resp.status_code}, body={resp.text})"
        )

    return resp.json()


# ================================
# Fonctions publiques : search & getArticle
# ================================

async def lf_search(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Wrapper de la méthode POST /consult/search.
    """
    return await _post_legifrance("search", payload)


async def lf_get_article(legiarti_id: str) -> Dict[str, Any]:
    """
    Wrapper de la méthode POST /consult/getArticle.
    Payload:
      { "id": "LEGIARTI..." }
    """
    return await _post_legifrance("getArticle", {"id": legiarti_id})
