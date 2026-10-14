"""
Modelos de los datos maestros (vehículos, carreta, conductores, proveedores,
transportistas y concesiones).

Los maestros no se borran físicamente: se desactivan para preservar referencias
históricas en pesajes.
"""

from database.conexion import lectura, transaccion
from models.base import ModeloBase, ReglaNegocioError


class MaestroModelo(ModeloBase):
    campos_vista = ()
    campo_orden = None

    @classmethod
    def activos(cls, conexion=None):
        columnas = ", ".join((cls.pk, *cls.campos_vista))
        with lectura(conexion) as cx:
            filas = cx.execute(
                f"SELECT {columnas} FROM {cls.tabla} "
                f"WHERE activo = 1 ORDER BY {cls.campo_orden}"
            ).fetchall()
        return [tuple(f) for f in filas]

    @classmethod
    def delete_by_id(cls, id_, conexion=None):
        return cls.update_by_id(id_, {"activo": 0}, conexion)

    @classmethod
    def activar(cls, id_, conexion=None):
        return cls.update_by_id(id_, {"activo": 1}, conexion)


class VehiculoModel(MaestroModelo):
    tabla = "vehiculos"
    pk = "id_vehiculo"
    columnas = ("placa", "id_externo", "activo")
    campos_vista = ("placa",)
    campo_orden = "placa"


class CarretaModel(MaestroModelo):
    tabla = "carretas"
    pk = "id_carreta"
    columnas = ("placa", "id_externo", "activo")
    campos_vista = ("placa",)
    campo_orden = "placa"


class ConductorModel(MaestroModelo):
    tabla = "conductores"
    pk = "id_conductor"
    columnas = ("nombre", "brevete", "id_externo", "activo")
    campos_vista = ("nombre", "brevete")
    campo_orden = "nombre"

    @classmethod
    def sincronizar_desde_api(cls, registros):
        """
        Sincroniza una lista de conductores procedente del API.

        id_externo conserva el id_conductor de MySQL. El id_conductor local
        de SQLite no se reemplaza porque puede estar referenciado por pesajes.
        La operación completa es atómica: si un registro falla, se revierte.
        """
        if not isinstance(registros, list):
            raise ValueError("La API no devolvió una lista de conductores.")

        insertados = 0
        actualizados = 0
        desactivados = 0

        with transaccion() as cx:
            ids_recibidos = set()

            for registro in registros:
                if not isinstance(registro, dict):
                    raise ValueError("La API devolvió un conductor con formato inválido.")

                id_remoto = registro.get("id_conductor")
                nombre = str(registro.get("nombre_conductor") or "").strip()

                # La licencia puede ser NULL en MySQL, pero la columna local
                # brevete es NOT NULL. Como respaldo usamos el documento.
                brevete = str(
                    registro.get("numero_licencia")
                    or registro.get("numero_documento")
                    or ""
                ).strip()

                if id_remoto is None or not nombre or not brevete:
                    raise ValueError(
                        "Un conductor de la API no contiene id, nombre o "
                        "licencia/documento válido."
                    )

                id_externo = str(id_remoto)
                ids_recibidos.add(id_externo)

                estado = registro.get("estado", 1)
                eliminado = registro.get("deleted_at") not in (None, "", False)
                activo = 1 if str(estado).strip() in ("1", "True", "true") and not eliminado else 0

                existente = cx.execute(
                    f"SELECT {cls.pk}, nombre, brevete, activo, id_externo "
                    f"FROM {cls.tabla} WHERE id_externo = ?",
                    (id_externo,),
                ).fetchone()

                # Si el conductor ya existía localmente por brevete, lo vinculamos
                # con el ID remoto en vez de crear un duplicado.
                if existente is None:
                    existente = cx.execute(
                        f"SELECT {cls.pk}, nombre, brevete, activo, id_externo "
                        f"FROM {cls.tabla} WHERE brevete = ?",
                        (brevete,),
                    ).fetchone()

                datos = {
                    "nombre": nombre,
                    "brevete": brevete,
                    "id_externo": id_externo,
                    "activo": activo,
                }

                if existente:
                    cambio = (
                        existente["nombre"] != nombre
                        or existente["brevete"] != brevete
                        or existente["activo"] != activo
                        or existente["id_externo"] != id_externo
                    )
                    if cambio:
                        cls.update_by_id(existente[cls.pk], datos, cx)
                        if existente["activo"] != 0 and activo == 0:
                            desactivados += 1
                        else:
                            actualizados += 1
                else:
                    cls.add(datos, cx)
                    insertados += 1

        return {
            "insertados": insertados,
            "actualizados": actualizados,
            "desactivados": desactivados,
        }


class ProveedorModel(MaestroModelo):
    tabla = "proveedores"
    pk = "id_proveedor"
    columnas = ("nombre", "ruc", "id_externo", "activo")
    campos_vista = ("nombre", "ruc")
    campo_orden = "nombre"


class TransportistaModel(MaestroModelo):
    tabla = "transportistas"
    pk = "id_transportista"
    columnas = ("nombre", "ruc", "id_externo", "activo")
    campos_vista = ("nombre", "ruc")
    campo_orden = "nombre"


class ConcesionModel(MaestroModelo):
    tabla = "concesiones"
    pk = "id_concesion"
    columnas = ("nombre", "codigo", "id_externo", "activo")
    campos_vista = ("nombre", "codigo")
    campo_orden = "nombre"
