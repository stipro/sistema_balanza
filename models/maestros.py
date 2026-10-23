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

    @classmethod
    def sincronizar_desde_api(cls, registros):
        """
        Sincroniza solo CAMION y TRACTO desde GET /api/vehiculos.
        Las CARRETA se sincronizan mediante CarretaModel.
        Conserva el ID local y guarda el ID remoto en id_externo.
        """
        if not isinstance(registros, list):
            raise ValueError("La API no devolvió una lista de vehículos.")

        insertados = 0
        actualizados = 0
        desactivados = 0

        with transaccion() as cx:
            for registro in registros:
                if not isinstance(registro, dict):
                    raise ValueError("La API devolvió un vehículo con formato inválido.")

                tipo = str(registro.get("tipo_vehiculo") or "").strip().upper()
                if tipo == "CARRETA":
                    # Si una versión anterior del programa guardó esta carreta
                    # en vehiculos, desactivarla sin borrarla ni cambiar su PK.
                    id_remoto_carreta = registro.get("id_vehiculo")
                    placa_carreta = str(registro.get("placa") or "").strip().upper()
                    fila_carreta = None
                    if id_remoto_carreta is not None:
                        fila_carreta = cx.execute(
                            f"SELECT {cls.pk}, activo FROM {cls.tabla} WHERE id_externo = ?",
                            (str(id_remoto_carreta),),
                        ).fetchone()
                    if fila_carreta is None and placa_carreta:
                        fila_carreta = cx.execute(
                            f"SELECT {cls.pk}, activo FROM {cls.tabla} WHERE placa = ?",
                            (placa_carreta,),
                        ).fetchone()
                    if fila_carreta and fila_carreta["activo"] != 0:
                        cls.update_by_id(fila_carreta[cls.pk], {"activo": 0}, cx)
                        desactivados += 1
                    continue
                if tipo not in ("CAMION", "TRACTO"):
                    raise ValueError(
                        f"Tipo de vehículo inválido para la placa "
                        f"{registro.get('placa') or '(sin placa)'}: {tipo or '(vacío)'}."
                    )

                id_remoto = registro.get("id_vehiculo")
                placa = str(registro.get("placa") or "").strip().upper()
                if id_remoto is None or not placa:
                    raise ValueError("Un vehículo no contiene un ID o una placa válida.")

                id_externo = str(id_remoto)
                existente = cx.execute(
                    f"SELECT {cls.pk}, placa, id_externo, activo "
                    f"FROM {cls.tabla} WHERE id_externo = ?",
                    (id_externo,),
                ).fetchone()

                if existente is None:
                    existente = cx.execute(
                        f"SELECT {cls.pk}, placa, id_externo, activo "
                        f"FROM {cls.tabla} WHERE placa = ?",
                        (placa,),
                    ).fetchone()

                datos = {"placa": placa, "id_externo": id_externo, "activo": 1}
                if existente:
                    cambio = any(existente[campo] != valor for campo, valor in datos.items())
                    if cambio:
                        cls.update_by_id(existente[cls.pk], datos, cx)
                        actualizados += 1
                else:
                    cls.add(datos, cx)
                    insertados += 1

        return {
            "insertados": insertados,
            "actualizados": actualizados,
            "desactivados": desactivados,
        }


class CarretaModel(MaestroModelo):
    tabla = "carretas"
    pk = "id_carreta"
    columnas = ("placa", "id_externo", "activo")
    campos_vista = ("placa",)
    campo_orden = "placa"

    @classmethod
    def sincronizar_desde_api(cls, registros):
        """
        Sincroniza únicamente los registros CARRETA del catálogo comercial.
        Conserva el ID local y guarda el ID de MySQL en id_externo.
        """
        if not isinstance(registros, list):
            raise ValueError("La API no devolvió una lista de vehículos.")

        insertados = 0
        actualizados = 0

        with transaccion() as cx:
            for registro in registros:
                if not isinstance(registro, dict):
                    raise ValueError("La API devolvió un vehículo con formato inválido.")

                tipo = str(registro.get("tipo_vehiculo") or "").strip().upper()
                if tipo != "CARRETA":
                    continue

                id_remoto = registro.get("id_vehiculo")
                placa = str(registro.get("placa") or "").strip().upper()
                if id_remoto is None or not placa:
                    raise ValueError("Una carreta no contiene un ID o una placa válida.")

                id_externo = str(id_remoto)
                existente = cx.execute(
                    f"SELECT {cls.pk}, placa, id_externo, activo "
                    f"FROM {cls.tabla} WHERE id_externo = ?",
                    (id_externo,),
                ).fetchone()

                if existente is None:
                    existente = cx.execute(
                        f"SELECT {cls.pk}, placa, id_externo, activo "
                        f"FROM {cls.tabla} WHERE placa = ?",
                        (placa,),
                    ).fetchone()

                datos = {"placa": placa, "id_externo": id_externo, "activo": 1}
                if existente:
                    cambio = any(existente[campo] != valor for campo, valor in datos.items())
                    if cambio:
                        cls.update_by_id(existente[cls.pk], datos, cx)
                        actualizados += 1
                else:
                    cls.add(datos, cx)
                    insertados += 1

        return {
            "insertados": insertados,
            "actualizados": actualizados,
            "desactivados": 0,
        }


class ConductorModel(MaestroModelo):
    tabla = "conductores"
    pk = "id_conductor"
    columnas = ("nombre", "dni", "brevete", "domicilio", "id_externo", "activo")
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
                licencia_api = str(registro.get("numero_licencia") or "").strip()
                dni_api = str(registro.get("numero_documento") or "").strip()
                dni = (
                    licencia_api[1:]
                    if licencia_api[:1].isalpha()
                    else dni_api or None
                )

                # La licencia puede ser NULL en MySQL, pero la columna local
                # brevete es NOT NULL. Como respaldo usamos el documento.
                brevete = str(
                    licencia_api
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
                    f"SELECT {cls.pk}, nombre, dni, brevete, activo, id_externo "
                    f"FROM {cls.tabla} WHERE id_externo = ?",
                    (id_externo,),
                ).fetchone()

                # Si el conductor ya existía localmente por brevete, lo vinculamos
                # con el ID remoto en vez de crear un duplicado.
                if existente is None:
                    existente = cx.execute(
                        f"SELECT {cls.pk}, nombre, dni, brevete, activo, id_externo "
                        f"FROM {cls.tabla} WHERE brevete = ?",
                        (brevete,),
                    ).fetchone()

                datos = {
                    "nombre": nombre,
                    "dni": dni,
                    "brevete": brevete,
                    "id_externo": id_externo,
                    "activo": activo,
                }

                if existente:
                    cambio = (
                        existente["nombre"] != nombre
                        or existente["dni"] != dni
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


    @classmethod
    def sincronizar_desde_api(cls, registros):
        """
        Sincroniza proveedores activos devueltos por GET /api/proveedores.
        Guarda el ID remoto en id_externo y conserva el PK local de SQLite.
        Los proveedores ausentes no se desactivan porque la API solo devuelve activos.
        """
        if not isinstance(registros, list):
            raise ValueError("La API no devolvió una lista de proveedores.")

        insertados = 0
        actualizados = 0

        with transaccion() as cx:
            for registro in registros:
                if not isinstance(registro, dict):
                    raise ValueError("La API devolvió un proveedor con formato inválido.")

                id_remoto = registro.get("id_proveedor")
                ruc = str(registro.get("ruc") or "").strip()
                nombre = str(registro.get("razon_social") or "").strip()

                if id_remoto is None or not ruc or not nombre:
                    raise ValueError(
                        "Un proveedor de la API no contiene id_proveedor, RUC "
                        "o razon_social válido."
                    )

                id_externo = str(id_remoto)
                existente = cx.execute(
                    f"SELECT {cls.pk}, nombre, ruc, activo, id_externo "
                    f"FROM {cls.tabla} WHERE id_externo = ?",
                    (id_externo,),
                ).fetchone()

                # Si ya existía localmente por RUC, vincularlo para evitar duplicados.
                if existente is None:
                    existente = cx.execute(
                        f"SELECT {cls.pk}, nombre, ruc, activo, id_externo "
                        f"FROM {cls.tabla} WHERE ruc = ?",
                        (ruc,),
                    ).fetchone()

                datos = {
                    "nombre": nombre,
                    "ruc": ruc,
                    "id_externo": id_externo,
                    "activo": 1,
                }

                if existente:
                    cambio = (
                        existente["nombre"] != nombre
                        or existente["ruc"] != ruc
                        or existente["activo"] != 1
                        or existente["id_externo"] != id_externo
                    )
                    if cambio:
                        cls.update_by_id(existente[cls.pk], datos, cx)
                        actualizados += 1
                else:
                    cls.add(datos, cx)
                    insertados += 1

        return {
            "insertados": insertados,
            "actualizados": actualizados,
            "desactivados": 0,
        }


class TransportistaModel(MaestroModelo):
    tabla = "transportistas"
    pk = "id_transportista"
    columnas = ("nombre", "ruc", "id_externo", "activo")
    campos_vista = ("nombre", "ruc")
    campo_orden = "nombre"

    @classmethod
    def sincronizar_desde_api(cls, registros):
        """
        Sincroniza transportistas activos devueltos por GET /api/transportistas.

        El ID remoto se guarda en id_externo. Se conserva el PK local para
        mantener intactas las referencias de los pesajes históricos.
        Los ausentes no se desactivan porque la API entrega solo activos.
        """
        if not isinstance(registros, list):
            raise ValueError("La API no devolvió una lista de transportistas.")

        insertados = 0
        actualizados = 0

        with transaccion() as cx:
            for registro in registros:
                if not isinstance(registro, dict):
                    raise ValueError(
                        "La API devolvió un transportista con formato inválido."
                    )

                id_remoto = registro.get("id_transportista")
                ruc = str(registro.get("ruc_transportista") or "").strip()
                nombre = str(registro.get("nombre_transportista") or "").strip()

                if id_remoto is None or not ruc or not nombre:
                    raise ValueError(
                        "Un transportista de la API no contiene "
                        "id_transportista, RUC o nombre válido."
                    )

                id_externo = str(id_remoto)

                existente = cx.execute(
                    f"SELECT {cls.pk}, nombre, ruc, activo, id_externo "
                    f"FROM {cls.tabla} WHERE id_externo = ?",
                    (id_externo,),
                ).fetchone()

                # Vincular registros locales previos por RUC para evitar duplicados.
                if existente is None:
                    existente = cx.execute(
                        f"SELECT {cls.pk}, nombre, ruc, activo, id_externo "
                        f"FROM {cls.tabla} WHERE ruc = ?",
                        (ruc,),
                    ).fetchone()

                datos = {
                    "nombre": nombre,
                    "ruc": ruc,
                    "id_externo": id_externo,
                    "activo": 1,
                }

                if existente:
                    cambio = (
                        existente["nombre"] != nombre
                        or existente["ruc"] != ruc
                        or existente["activo"] != 1
                        or existente["id_externo"] != id_externo
                    )
                    if cambio:
                        cls.update_by_id(existente[cls.pk], datos, cx)
                        actualizados += 1
                else:
                    cls.add(datos, cx)
                    insertados += 1

        return {
            "insertados": insertados,
            "actualizados": actualizados,
            "desactivados": 0,
        }


class ConcesionModel(MaestroModelo):
    tabla = "concesiones"
    pk = "id_concesion"
    columnas = (
        "nombre", "codigo", "distrito", "provincia", "departamento",
        "id_externo", "activo"
    )
    campos_vista = ("nombre","codigo","distrito","provincia","departamento",)
    campo_orden = "nombre"

    @classmethod
    def sincronizar_desde_api(cls, registros):
        """
        Sincroniza concesiones activas desde GET /api/concesiones.
        Conserva el ID local para no romper referencias de pesajes históricos.
        """
        if not isinstance(registros, list):
            raise ValueError("La API no devolvió una lista de concesiones.")

        insertados = 0
        actualizados = 0

        with transaccion() as cx:
            for registro in registros:
                if not isinstance(registro, dict):
                    raise ValueError(
                        "La API devolvió una concesión con formato inválido."
                    )

                id_remoto = registro.get("id_concesion")
                codigo = str(registro.get("codigo_concesion") or "").strip()
                nombre = str(registro.get("nombre_concesion") or "").strip()
                distrito = str(registro.get("distrito_concesion") or "").strip()
                provincia = str(registro.get("provincia_concesion") or "").strip()
                departamento = str(registro.get("departamento_concesion") or "").strip()

                if id_remoto is None or not codigo or not nombre:
                    raise ValueError(
                        "Una concesión de la API no contiene "
                        "id_concesion, código o nombre válido."
                    )

                id_externo = str(id_remoto)
                existente = cx.execute(
                    f"SELECT {cls.pk}, nombre, codigo, distrito, provincia, "
                    f"departamento, activo, id_externo FROM {cls.tabla} "
                    "WHERE id_externo = ?",
                    (id_externo,),
                ).fetchone()

                # Si ya existía una concesión local, vincularla por código y
                # conservar su PK para no alterar las referencias históricas.
                if existente is None:
                    existente = cx.execute(
                        f"SELECT {cls.pk}, nombre, codigo, distrito, provincia, "
                        f"departamento, activo, id_externo FROM {cls.tabla} "
                        "WHERE codigo = ?",
                        (codigo,),
                    ).fetchone()

                datos = {
                    "nombre": nombre,
                    "codigo": codigo,
                    "distrito": distrito,
                    "provincia": provincia,
                    "departamento": departamento,
                    "id_externo": id_externo,
                    "activo": 1,
                }

                if existente:
                    cambio = any(
                        existente[campo] != valor
                        for campo, valor in datos.items()
                    )
                    if cambio:
                        cls.update_by_id(existente[cls.pk], datos, cx)
                        actualizados += 1
                else:
                    cls.add(datos, cx)
                    insertados += 1

        return {
            "insertados": insertados,
            "actualizados": actualizados,
            "desactivados": 0,
        }
