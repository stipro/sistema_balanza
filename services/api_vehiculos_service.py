"""
Cliente HTTP del endpoint de vehículos del sistema comercial.

Endpoint: GET /vehiculos
Configuración: BALANZA_API_BASE_URL y BALANZA_API_TOKEN en .env
"""

import os
import requests

from services.api_conductores_service import cargar_configuracion


cargar_configuracion()


class ApiVehiculosService:
    TIMEOUT = (5, 30)

    @classmethod
    def obtener_vehiculos(cls):
        base_url = os.getenv(
            "BALANZA_API_BASE_URL",
            "http://localhost:8848/Bee-Framework/api",
        ).strip().rstrip("/")

        token = os.getenv("BALANZA_API_TOKEN", "").strip()

        if not base_url:
            raise RuntimeError(
                "Configure la variable BALANZA_API_BASE_URL."
            )

        if not token:
            raise RuntimeError(
                "Falta configurar BALANZA_API_TOKEN."
            )

        url = f"{base_url}/vehiculos"

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
            raise RuntimeError(
                "La API de vehículos tardó demasiado en responder."
            ) from exc

        except requests.ConnectionError as exc:
            raise RuntimeError(
                "No se pudo conectar con la API de vehículos. "
                "Verifique la conexión, el servidor y la URL."
            ) from exc

        except requests.HTTPError as exc:
            codigo = (
                exc.response.status_code
                if exc.response is not None
                else "desconocido"
            )
            raise RuntimeError(
                f"La API de vehículos respondió con HTTP {codigo}."
            ) from exc

        except requests.RequestException as exc:
            raise RuntimeError(
                f"Error al consultar vehículos: {exc}"
            ) from exc

        try:
            payload = respuesta.json()
        except ValueError as exc:
            raise RuntimeError(
                "La API de vehículos no devolvió JSON válido."
            ) from exc

        if not isinstance(payload, dict):
            raise RuntimeError(
                "La respuesta de vehículos tiene un formato inesperado."
            )

        if payload.get("error") is True:
            raise RuntimeError(
                payload.get("msg") or "La API informó un error."
            )

        registros = payload.get("data")

        if registros is None:
            registros = payload.get("result")

        if isinstance(registros, dict):
            registros = registros.get(
                "data",
                registros.get("vehiculos"),
            )

        if not isinstance(registros, list):
            raise RuntimeError(
                "La respuesta de la API no contiene una lista de vehículos."
            )

        return registros