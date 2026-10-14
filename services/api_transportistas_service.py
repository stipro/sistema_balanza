"""Cliente HTTP para el catálogo de transportistas del Sistema Comercial."""

import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv


def _cargar_configuracion():
    # En desarrollo, el .env se encuentra en la raíz del proyecto.
    # En el ejecutable PyInstaller, se encuentra junto al .exe.
    if getattr(sys, "frozen", False):
        carpeta_base = Path(sys.executable).resolve().parent
    else:
        carpeta_base = Path(__file__).resolve().parents[1]

    load_dotenv(dotenv_path=carpeta_base / ".env", override=False)


_cargar_configuracion()


class ApiTransportistasService:
    TIMEOUT = 20

    @classmethod
    def obtener_transportistas(cls):
        base_url = os.getenv(
            "BALANZA_API_BASE_URL",
            "http://localhost:8848/Bee-Framework/api",
        ).strip().rstrip("/")
        token = os.getenv("BALANZA_API_TOKEN", "").strip()

        if not base_url:
            raise RuntimeError("Falta configurar BALANZA_API_BASE_URL en el archivo .env.")
        if not token:
            raise RuntimeError("Falta configurar BALANZA_API_TOKEN en el archivo .env.")

        url = f"{base_url}/transportistas"
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
        }

        try:
            respuesta = requests.get(
                url,
                headers=headers,
                timeout=cls.TIMEOUT,
            )
            respuesta.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(
                f"No se pudo consultar la API de transportistas ({url}): {exc}"
            ) from exc

        try:
            payload = respuesta.json()
        except ValueError as exc:
            raise RuntimeError("La API de transportistas devolvió una respuesta no JSON.") from exc

        if not isinstance(payload, dict):
            raise RuntimeError("La respuesta de la API de transportistas tiene un formato inválido.")

        if payload.get("error") is True:
            mensaje = payload.get("msg") or "La API reportó un error."
            raise RuntimeError(f"API de transportistas: {mensaje}")

        # Formato esperado de Bee Framework: {"status": 200, "error": false, "data": [...]}
        registros = payload.get("data", payload.get("result"))

        # Compatibilidad si data viene envuelto nuevamente: {"data": {"data": [...]}}
        if isinstance(registros, dict):
            registros = registros.get("data", registros.get("result"))

        if not isinstance(registros, list):
            raise RuntimeError(
                "La API no devolvió una lista válida en el campo 'data'."
            )

        return registros
