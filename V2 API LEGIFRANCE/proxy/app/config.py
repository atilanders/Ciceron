import os
from dotenv import load_dotenv

# Charge le fichier .env à la racine du projet
load_dotenv()

# ================================
# CONFIGURATION PISTE / LÉGIFRANCE
# ================================

PISTE_CLIENT_ID = os.getenv("PISTE_CLIENT_ID")
PISTE_CLIENT_SECRET = os.getenv("PISTE_CLIENT_SECRET")

PISTE_TOKEN_URL = os.getenv(
    "PISTE_TOKEN_URL",
    "https://sandbox-oauth.piste.gouv.fr/api/oauth/token"
)

LEGIFRANCE_API_BASE = os.getenv(
    "LEGIFRANCE_API_BASE",
    "https://api.piste.gouv.fr/dila/legifrance-beta/lf-engine-app/consult"
)

# ================================
# PARAMÈTRES GÉNÉRAUX
# ================================

REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "30"))


def check_config():
    """
    Vérifie que les variables critiques sont bien présentes.
    Appelée au démarrage pour éviter des erreurs silencieuses.
    """
    missing = []

    if not PISTE_CLIENT_ID:
        missing.append("PISTE_CLIENT_ID")

    if not PISTE_CLIENT_SECRET:
        missing.append("PISTE_CLIENT_SECRET")

    if missing:
        raise RuntimeError(
            f"Configuration manquante dans .env : {', '.join(missing)}"
        )
