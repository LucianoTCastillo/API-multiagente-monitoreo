import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from langchain_groq import ChatGroq


# Encuentra el .env en la raíz del proyecto.
PROJECT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_DIR / ".env", override=False)


def get_redis_url() -> str:
    """Obtiene la dirección del servidor Redis."""
    url = os.getenv(
        "REDIS_URL",
        "redis://localhost:6379/0",
    ).strip()

    if not url:
        raise ValueError("Falta configurar REDIS_URL en el .env.")

    return url


@lru_cache(maxsize=1)
def get_llm() -> ChatGroq:
    """Crea y reutiliza el cliente del modelo de Groq."""
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    model = os.getenv("GROQ_MODEL", "").strip()

    if not api_key or api_key == "PEGA_AQUI_TU_CLAVE":
        raise ValueError(
            "Configurá tu clave en GROQ_API_KEY dentro del .env."
        )

    if not model:
        raise ValueError(
            "Configurá el nombre del modelo en GROQ_MODEL "
            "dentro del .env."
        )

    return ChatGroq(
        api_key=api_key,
        model=model,
        temperature=0,
        max_tokens=512,
        timeout=60,
        max_retries=20,
    )