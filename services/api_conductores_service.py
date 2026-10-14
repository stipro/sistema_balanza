"""
Cliente HTTP del endpoint de conductores del sistema comercial.

Configuración: lee el archivo .env junto al ejecutable (o en la raíz del proyecto).
  BALANZA_API_BASE_URL  Ej.: http://localhost:8848/Bee-Framework/api
  BALANZA_API_TOKEN     Token Bearer de Bee Framework

Las variables de entorno definidas en Windows tienen prioridad sobre los valores de .env.
"""

import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv


def cargar_configuracion():
    """
    Carga .env desde la carpeta del .exe cuando se ejecuta empaquetado.
    En desarrollo, lo busca en la raíz del proyecto.
    """
    if getattr(sys, "frozen", False):
        carpeta_base = Path(sys.executable).resolve().parent
    else:
        carpeta_base = Path(__file__).resolve().parents[1]

    archivo_env = carpeta_base / ".env"
    load_dotenv(dotenv_path=archivo_env, override=False)


cargar_configuracion()


class ApiConductoresService:
    TIMEOUT = (5, 30)

    @classmethod
    def obtener_conductores(cls):
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

        url = f"{base_url}/conductores"
        try:
            respuesta = requests.get(
                url,
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

        # Bee Framework puede envolver el resultado en la propiedad data.
        registros = payload.get("data")
        if registros is None:
            registros = payload.get("result")

        if isinstance(registros, dict):
            # Compatibilidad con APIs que envuelven la lista dentro de data.data.
            registros = registros.get("data", registros.get("conductores"))

        if not isinstance(registros, list):
            mensaje = payload.get("message") or payload.get("mensaje") or ""
            raise RuntimeError(
                "La respuesta no contiene una lista en 'data'. "
                + (f"Detalle de la API: {mensaje}" if mensaje else "")
            )

        return registros
