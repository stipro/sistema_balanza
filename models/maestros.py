"""
Modelos de los datos maestros (vehículos, carreta, conductores, proveedores,
transportistas y concesiones).

Los maestros NUNCA se borran: delete_by_id() solo los desactiva (activo = 0),
para no romper ingresos e informes históricos.
"""

from database.conexion import lectura
from models.base import ModeloBase


class MaestroModelo(ModeloBase):

    campos_vista = ()  # columnas que la vista necesita, en ese orden
    campo_orden = None

    @classmethod
    def activos(cls, conexion=None):
        """
        Devuelve TUPLAS (id, campos_vista...) de los registros activos.
        Es el formato que ya usa la vista (vehiculos: (id, placa),
        proveedores: (id, nombre, ruc), etc.).
        """

        columnas = ", ".join((cls.pk, *cls.campos_vista))

        with lectura(conexion) as cx:
            filas = cx.execute(
                f"SELECT {columnas} FROM {cls.tabla} "
                f"WHERE activo = 1 ORDER BY {cls.campo_orden}"
            ).fetchall()

        return [tuple(f) for f in filas]

    @classmethod
    def delete_by_id(cls, id_, conexion=None):
        """Desactiva (no borra)."""

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
