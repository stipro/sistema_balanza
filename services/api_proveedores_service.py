"""
Cliente HTTP del endpoint de proveedores del sistema comercial.
Usa BALANZA_API_BASE_URL y BALANZA_API_TOKEN del archivo .env.
"""

import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv


def cargar_configuracion():
    if getattr(sys, "frozen", False):
        carpeta_base = Path(sys.executable).resolve().parent
    else:
        carpeta_base = Path(__file__).resolve().parents[1]
    load_dotenv(dotenv_path=carpeta_base / ".env", override=False)


cargar_configuracion()


class ApiProveedoresService:
    TIMEOUT = (5, 30)

    @classmethod
    def obtener_proveedores(cls):
        base_url = os.getenv(
            "BALANZA_API_BASE_URL",
            "http://localhost:8848/Bee-Framework/api",
        ).strip().rstrip("/")
        token = os.getenv("BALANZA_API_TOKEN", "").strip()

        if not base_url:
            raise RuntimeError("Configure la variable BALANZA_API_BASE_URL.")
        if not token:
            raise RuntimeError(
                "Falta configurar BALANZA_API_TOKEN con el token Bearer de la API."
            )

        try:
            respuesta = requests.get(
                f"{base_url}/proveedores",
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {token}",
                },
                timeout=cls.TIMEOUT,
            )
            respuesta.raise_for_status()
        except requests.Timeout as exc:
            raise RuntimeError("La API tardó demasiado en responder.") from exc
        except requests.ConnectionError as exc:
            raise RuntimeError(
                "No se pudo conectar con la API. Verifique Internet, servidor y URL."
            ) from exc
        except requests.HTTPError as exc:
            codigo = exc.response.status_code if exc.response is not None else "desconocido"
            raise RuntimeError(f"La API respondió con HTTP {codigo}.") from exc
        except requests.RequestException as exc:
            raise RuntimeError(f"Error al consultar la API: {exc}") from exc

        try:
            payload = respuesta.json()
        except ValueError as exc:
            raise RuntimeError("La API no devolvió JSON válido.") from exc

        if not isinstance(payload, dict):
            raise RuntimeError("La respuesta de la API tiene un formato inesperado.")

        registros = payload.get("data")
        if registros is None:
            registros = payload.get("result")
        if isinstance(registros, dict):
            registros = registros.get("data", registros.get("proveedores"))

        if not isinstance(registros, list):
            mensaje = payload.get("message") or payload.get("mensaje") or ""
            raise RuntimeError(
                "La respuesta no contiene una lista en 'data'. "
                + (f"Detalle de la API: {mensaje}" if mensaje else "")
            )
        return registros
