"""
Modelo base (equivalente a tu clase Model de PHP).

Todos los métodos son @classmethod: no hace falta instanciar.

    PesajeModel.by_id(3)
    PesajeModel.add({"ticket": 100001})
    PesajeModel.update_by_id(3, {"id_vehiculo": 2})
    PesajeModel.delete_by_id(3)
    PesajeModel.all({"estado": "EN_PROCESO"}, orden="ticket DESC")

Cada tabla hereda y define: tabla, pk, columnas (editables), uuid_col
(opcional) y con_timestamps.

Todos los métodos aceptan `conexion=None`:
    - sin conexión: abren la suya y hacen commit solos.
    - con conexión: participan en la transacción de quien la abrió.
"""

import sqlite3
import uuid

from database.conexion import ahora, lectura, transaccion


class ReglaNegocioError(ValueError):
    """
    Se lanza cuando una operación viola una regla del negocio
    (por ejemplo: capturar sobre un ingreso ya confirmado).
    El mensaje está pensado para mostrarse tal cual al usuario.
    """


class ModeloBase:

    tabla = None
    pk = None
    columnas = ()  # columnas que se pueden escribir
    uuid_col = None  # columna UUID (se genera sola al crear)
    con_timestamps = True  # created_at / updated_at

    # AUXILIARES
    @classmethod
    def solo_columnas(cls, datos, excluir=()):
        """Filtra un dict dejando solo las columnas editables del modelo."""

        return {
            k: v for k, v in datos.items() if k in cls.columnas and k not in excluir
        }

    @classmethod
    def _validar_columnas(cls, datos):

        desconocidas = set(datos) - set(cls.columnas)

        if desconocidas:
            raise ValueError(
                f"Columnas no permitidas en {cls.tabla}: "
                f"{', '.join(sorted(desconocidas))}"
            )

    @classmethod
    def _columna_valida(cls, columna, cx):

        existentes = {f["name"] for f in cx.execute(f"PRAGMA table_info({cls.tabla})")}

        if columna not in existentes:
            raise ValueError(f"La columna '{columna}' no existe en {cls.tabla}.")

    @staticmethod
    def _a_dict(fila):

        return dict(fila) if fila is not None else None

    # CREATE
    @classmethod
    def add(cls, datos, conexion=None):
        """Inserta una fila y devuelve su ID."""

        cls._validar_columnas(datos)

        valores = dict(datos)

        if cls.uuid_col:
            valores[cls.uuid_col] = str(uuid.uuid4())

        if cls.con_timestamps:
            t = ahora()
            valores["created_at"] = t
            valores["updated_at"] = t

        columnas = ", ".join(valores)
        marcas = ", ".join("?" for _ in valores)

        try:
            with transaccion(conexion) as cx:
                cur = cx.execute(
                    f"INSERT INTO {cls.tabla} ({columnas}) VALUES ({marcas})",
                    tuple(valores.values()),
                )
                return cur.lastrowid

        except sqlite3.IntegrityError as e:
            raise ReglaNegocioError(f"No se pudo guardar en {cls.tabla}: {e}") from e

    # READ
    @classmethod
    def by_id(cls, id_, conexion=None):
        """Devuelve la fila como dict, o None si no existe."""

        with lectura(conexion) as cx:
            fila = cx.execute(
                f"SELECT * FROM {cls.tabla} WHERE {cls.pk} = ?", (id_,)
            ).fetchone()

        return cls._a_dict(fila)

    @classmethod
    def all(cls, filtros=None, orden=None, limite=None, conexion=None):
        """
        Devuelve una lista de dicts.

        filtros: {"estado": "EN_PROCESO", "id_pesaje": 3}  (None -> IS NULL)
        orden:   "ticket" o "ticket DESC"
        """

        sql = f"SELECT * FROM {cls.tabla}"
        params = []

        with lectura(conexion) as cx:

            if filtros:
                condiciones = []

                for columna, valor in filtros.items():
                    cls._columna_valida(columna, cx)

                    if valor is None:
                        condiciones.append(f"{columna} IS NULL")
                    else:
                        condiciones.append(f"{columna} = ?")
                        params.append(valor)

                sql += " WHERE " + " AND ".join(condiciones)

            if orden:
                columna, _, sentido = orden.partition(" ")
                sentido = sentido.strip().upper()

                cls._columna_valida(columna, cx)

                if sentido not in ("", "ASC", "DESC"):
                    raise ValueError("Sentido de orden inválido.")

                sql += f" ORDER BY {columna} {sentido}".rstrip()

            if limite:
                sql += f" LIMIT {int(limite)}"

            filas = cx.execute(sql, params).fetchall()

        return [dict(f) for f in filas]

    # UPDATE
    @classmethod
    def update_by_id(cls, id_, datos, conexion=None):
        """Actualiza columnas. Devuelve True si la fila existía."""

        if not datos:
            return False

        cls._validar_columnas(datos)

        valores = dict(datos)

        if cls.con_timestamps:
            valores["updated_at"] = ahora()

        asignaciones = ", ".join(f"{c} = ?" for c in valores)

        try:
            with transaccion(conexion) as cx:
                cur = cx.execute(
                    f"UPDATE {cls.tabla} SET {asignaciones} WHERE {cls.pk} = ?",
                    (*valores.values(), id_),
                )
                return cur.rowcount > 0

        except sqlite3.IntegrityError as e:
            raise ReglaNegocioError(
                f"No se pudo actualizar {cls.tabla}: {e}"
            ) from e

    # DELETE
    @classmethod
    def delete_by_id(cls, id_, conexion=None):
        """Borra una fila. Devuelve True si existía."""

        try:
            with transaccion(conexion) as cx:
                cur = cx.execute(f"DELETE FROM {cls.tabla} WHERE {cls.pk} = ?", (id_,))
                return cur.rowcount > 0

        except sqlite3.IntegrityError as e:
            raise ReglaNegocioError(
                f"No se puede eliminar de {cls.tabla}: tiene datos asociados."
            ) from e
