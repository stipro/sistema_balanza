"""
Modelos del dominio de PESAJES (equivalente a tu userModel: varias tablas
del mismo tema en un solo archivo).

    PesajeModel           -> pesajes           (ingreso / camión)
    PesajeLoteModel       -> pesajes_lotes     (lotes del ingreso)
    PesajeRegistroModel   -> pesajes_registros (capturas físicas)
    ConfiguracionLotesModel -> configuracion_lotes (correlativo)

Las operaciones que tocan varias tablas a la vez (capturar, confirmar,
anular) están en services/pesaje_service.py.
"""

from datetime import datetime

from config.settings import TICKET_INICIAL
from database.conexion import ahora, lectura, transaccion
from models.base import ModeloBase, ReglaNegocioError

ESTADOS_INGRESO = ("EN_PROCESO", "CONFIRMADO", "ANULADO")
TIPOS_CARGA = ("SACO", "GRANEL")


# ======================================================================
# INGRESO / CAMIÓN  (tabla pesajes)
# Solo guarda datos comunes a todos sus lotes: ticket, vehículo, carreta,
# conductor y transportista.
# ======================================================================
class PesajeModel(ModeloBase):

    tabla = "pesajes"
    pk = "id_pesaje"
    uuid_col = "uuid_pesaje"
    columnas = (
        "ticket",
        "id_vehiculo",
        "id_carreta",
        "id_conductor",
        "id_transportista",
        "equipo",
    )

    @classmethod
    def siguiente_ticket(cls, conexion=None):

        with lectura(conexion) as cx:
            ultimo = cx.execute("SELECT MAX(ticket) FROM pesajes").fetchone()[0]

        base = TICKET_INICIAL if ultimo is None else int(ultimo)

        return base + 1

    @classmethod
    def by_ticket(cls, ticket, conexion=None):

        with lectura(conexion) as cx:
            fila = cx.execute(
                "SELECT * FROM pesajes WHERE ticket = ?", (ticket,)
            ).fetchone()

        return cls._a_dict(fila)

    @classmethod
    def pendientes(cls, conexion=None):
        """Ingresos EN_PROCESO con sus contadores (para 'Pesajes pendientes')."""

        with lectura(conexion) as cx:
            filas = cx.execute(
                """
                SELECT
                    p.id_pesaje,
                    p.ticket,
                    p.estado,
                    v.placa,
                    c.nombre AS chofer,
                    p.created_at,
                    (SELECT COUNT(*) FROM pesajes_lotes l
                      WHERE l.id_pesaje = p.id_pesaje
                        AND l.estado <> 'ANULADO') AS total_lotes,
                    (SELECT COUNT(*) FROM pesajes_lotes l
                      WHERE l.id_pesaje = p.id_pesaje
                        AND l.estado = 'COMPLETADO') AS lotes_completos,
                    (SELECT COUNT(*) FROM pesajes_registros r
                      WHERE r.id_pesaje = p.id_pesaje
                        AND r.anulado = 0) AS capturas
                FROM pesajes p
                LEFT JOIN vehiculos v ON v.id_vehiculo = p.id_vehiculo
                LEFT JOIN conductores c ON c.id_conductor = p.id_conductor
                WHERE p.estado = 'EN_PROCESO'
                ORDER BY p.ticket
                """
            ).fetchall()

        return [dict(f) for f in filas]

    @classmethod
    def update_by_id(cls, id_, datos, conexion=None):
        """Solo mientras el ingreso está EN_PROCESO."""

        if "ticket" in datos:
            raise ReglaNegocioError("El ticket no se puede modificar.")

        with transaccion(conexion) as cx:
            actual = cls.by_id(id_, cx)

            if actual is None:
                raise ReglaNegocioError("El ingreso no existe.")

            if actual["estado"] != "EN_PROCESO":
                raise ReglaNegocioError(
                    f"El ingreso {actual['ticket']} está {actual['estado']} "
                    f"y no se puede modificar."
                )

            return super().update_by_id(id_, datos, cx)

    @classmethod
    def cambiar_estado(cls, id_, estado, motivo=None, conexion=None):
        """Cambia el estado. Las reglas de negocio las valida el service."""

        if estado not in ESTADOS_INGRESO:
            raise ValueError(f"Estado inválido: {estado}")

        t = ahora()

        with transaccion(conexion) as cx:
            cx.execute(
                """
                UPDATE pesajes
                SET estado = ?,
                    fecha_confirmacion = CASE WHEN ? = 'CONFIRMADO'
                                              THEN ? ELSE NULL END,
                    motivo_anulacion = CASE WHEN ? = 'ANULADO'
                                            THEN ? ELSE NULL END,
                    updated_at = ?
                WHERE id_pesaje = ?
                """,
                (estado, estado, t, estado, motivo, t, id_),
            )

    @classmethod
    def marcar_sincronizado(cls, id_, conexion=None):

        t = ahora()

        with transaccion(conexion) as cx:
            cx.execute(
                "UPDATE pesajes SET sincronizado = 1, fecha_sincronizacion = ?, "
                "updated_at = ? WHERE id_pesaje = ?",
                (t, t, id_),
            )

    @classmethod
    def delete_by_id(cls, id_, conexion=None):
        """Solo un ticket vacío creado por error."""

        with transaccion(conexion) as cx:
            actual = cls.by_id(id_, cx)

            if actual is None:
                return False

            hijos = cx.execute(
                "SELECT (SELECT COUNT(*) FROM pesajes_lotes WHERE id_pesaje = ?) "
                "     + (SELECT COUNT(*) FROM pesajes_registros WHERE id_pesaje = ?)",
                (id_, id_),
            ).fetchone()[0]

            if actual["estado"] != "EN_PROCESO" or hijos:
                raise ReglaNegocioError(
                    "Solo se puede eliminar un ingreso vacío. "
                    "Use anular_ingreso() en los demás casos."
                )

            return super().delete_by_id(id_, cx)


# ======================================================================
# LOTES  (tabla pesajes_lotes)
# Todo lo propio del lote. Los pesos NO se guardan aquí: el lote apunta a
# dos capturas (bruto y tara) y el neto se calcula en v_lotes_detalle.
# ======================================================================
class PesajeLoteModel(ModeloBase):

    tabla = "pesajes_lotes"
    pk = "id_pesaje_lote"
    uuid_col = "uuid_lote"
    columnas = (
        "id_pesaje",
        "orden",
        "lote",
        "id_proveedor",
        "guia_proveedor",
        "guia_transportista",
        "id_concesion",
        "procedencia",
        "producto",
        "observacion",
        "tipo_carga",
        "cantidad_sacos",
        "priorizar_analisis",
    )

    @classmethod
    def _normalizar(cls, datos, actual=None):
        """Valida SACO/GRANEL y normaliza sacos y 'priorizar análisis'."""

        d = dict(datos)
        combinado = {**(actual or {}), **d}

        tipo = combinado.get("tipo_carga")

        if tipo not in TIPOS_CARGA:
            raise ReglaNegocioError("El tipo de carga debe ser SACO o GRANEL.")

        if tipo == "SACO":
            sacos = combinado.get("cantidad_sacos")

            if isinstance(sacos, bool) or not isinstance(sacos, int) or sacos <= 0:
                raise ReglaNegocioError(
                    "Un lote en SACOS debe tener una cantidad de sacos mayor que 0."
                )
        else:
            d["cantidad_sacos"] = None

        if "priorizar_analisis" in d:
            d["priorizar_analisis"] = 1 if d["priorizar_analisis"] else 0

        return d

    @classmethod
    def add(cls, datos, conexion=None):

        return super().add(cls._normalizar(datos), conexion)

    @classmethod
    def update_by_id(cls, id_, datos, conexion=None):

        bloqueadas = {"id_pesaje", "orden"} & set(datos)

        if bloqueadas:
            raise ReglaNegocioError(
                f"No se puede cambiar: {', '.join(sorted(bloqueadas))}."
            )

        with transaccion(conexion) as cx:
            actual = cls.by_id(id_, cx)

            if actual is None:
                raise ReglaNegocioError("El lote no existe.")

            if actual["estado"] == "ANULADO":
                raise ReglaNegocioError("Un lote anulado no se puede modificar.")

            if {"tipo_carga", "cantidad_sacos", "priorizar_analisis"} & set(datos):
                datos = cls._normalizar(datos, actual)

            return super().update_by_id(id_, datos, cx)

    @classmethod
    def delete_by_id(cls, id_, conexion=None):
        """Solo un lote sin capturas asignadas."""

        with transaccion(conexion) as cx:
            actual = cls.by_id(id_, cx)

            if actual is None:
                return False

            if actual["id_registro_bruto"] or actual["id_registro_tara"]:
                raise ReglaNegocioError(
                    "El lote ya tiene capturas asignadas. Use anular."
                )

            return super().delete_by_id(id_, cx)

    # CONSULTAS
    @classmethod
    def by_lote(cls, lote, conexion=None):

        with lectura(conexion) as cx:
            fila = cx.execute(
                "SELECT * FROM pesajes_lotes WHERE lote = ?", (lote,)
            ).fetchone()

        return cls._a_dict(fila)

    @classmethod
    def siguiente_orden(cls, id_pesaje, conexion=None):

        with lectura(conexion) as cx:
            return cx.execute(
                "SELECT COALESCE(MAX(orden), 0) + 1 "
                "FROM pesajes_lotes WHERE id_pesaje = ?",
                (id_pesaje,),
            ).fetchone()[0]

    @classmethod
    def by_pesaje(cls, id_pesaje, incluir_anulados=False, conexion=None):

        sql = "SELECT * FROM pesajes_lotes WHERE id_pesaje = ?"

        if not incluir_anulados:
            sql += " AND estado <> 'ANULADO'"

        with lectura(conexion) as cx:
            filas = cx.execute(sql + " ORDER BY orden", (id_pesaje,)).fetchall()

        return [dict(f) for f in filas]

    @classmethod
    def detalle(
        cls, id_pesaje, incluir_anulados=False, descendente=False, conexion=None
    ):
        """Filas de la vista v_lotes_detalle (bruto, tara y neto calculados)."""

        sql = "SELECT * FROM v_lotes_detalle WHERE id_pesaje = ?"

        if not incluir_anulados:
            sql += " AND estado <> 'ANULADO'"

        sql += " ORDER BY orden " + ("DESC" if descendente else "ASC")

        with lectura(conexion) as cx:
            filas = cx.execute(sql, (id_pesaje,)).fetchall()

        return [dict(f) for f in filas]

    @classmethod
    def abierto(cls, id_pesaje, conexion=None):
        """Lote con bruto asignado y sin tara (el que espera su 2ª pesada)."""

        with lectura(conexion) as cx:
            fila = cx.execute(
                "SELECT * FROM pesajes_lotes "
                "WHERE id_pesaje = ? AND estado = 'PENDIENTE' "
                "  AND id_registro_bruto IS NOT NULL "
                "  AND id_registro_tara IS NULL "
                "ORDER BY orden LIMIT 1",
                (id_pesaje,),
            ).fetchone()

        return cls._a_dict(fila)

    @classmethod
    def siguiente_sin_bruto(cls, id_pesaje, conexion=None):
        """Primer lote pendiente (por orden) que todavía no tiene bruto."""

        with lectura(conexion) as cx:
            fila = cx.execute(
                "SELECT * FROM pesajes_lotes "
                "WHERE id_pesaje = ? AND estado = 'PENDIENTE' "
                "  AND id_registro_bruto IS NULL "
                "ORDER BY orden LIMIT 1",
                (id_pesaje,),
            ).fetchone()

        return cls._a_dict(fila)

    # ENLACE CON LAS CAPTURAS
    @classmethod
    def asignar_bruto(cls, id_lote, id_registro, conexion=None):

        with transaccion(conexion) as cx:
            cx.execute(
                "UPDATE pesajes_lotes SET id_registro_bruto = ?, updated_at = ? "
                "WHERE id_pesaje_lote = ?",
                (id_registro, ahora(), id_lote),
            )

    @classmethod
    def asignar_tara(cls, id_lote, id_registro, conexion=None):
        """Asigna la tara y completa el lote."""

        with transaccion(conexion) as cx:
            cx.execute(
                "UPDATE pesajes_lotes "
                "SET id_registro_tara = ?, estado = 'COMPLETADO', updated_at = ? "
                "WHERE id_pesaje_lote = ?",
                (id_registro, ahora(), id_lote),
            )

    @classmethod
    def liberar_registro(cls, id_pesaje, id_registro, conexion=None):
        """
        Deshace el uso de una captura (al anularla): el lote que la tenía
        como tara vuelve a PENDIENTE y el que la tenía como bruto queda sin él.
        """

        t = ahora()

        with transaccion(conexion) as cx:
            cx.execute(
                "UPDATE pesajes_lotes "
                "SET id_registro_tara = NULL, estado = 'PENDIENTE', updated_at = ? "
                "WHERE id_pesaje = ? AND id_registro_tara = ? "
                "  AND estado <> 'ANULADO'",
                (t, id_pesaje, id_registro),
            )
            cx.execute(
                "UPDATE pesajes_lotes "
                "SET id_registro_bruto = NULL, updated_at = ? "
                "WHERE id_pesaje = ? AND id_registro_bruto = ? "
                "  AND estado <> 'ANULADO'",
                (t, id_pesaje, id_registro),
            )

    # ANULACIÓN
    @classmethod
    def anular(cls, id_lote, motivo, conexion=None):
        """
        Anula un lote que todavía NO tiene tara. Libera su bruto para que
        otro lote pueda usarlo.
        """

        if not motivo or not motivo.strip():
            raise ReglaNegocioError("Indique el motivo de la anulación.")

        with transaccion(conexion) as cx:
            lote = cls.by_id(id_lote, cx)

            if lote is None:
                raise ReglaNegocioError("El lote no existe.")

            if lote["estado"] == "ANULADO":
                raise ReglaNegocioError("El lote ya está anulado.")

            if lote["id_registro_tara"] is not None:
                raise ReglaNegocioError(
                    "El lote ya tiene su 2ª pesada. Anule la última captura "
                    "o el ingreso completo."
                )

            cx.execute(
                "UPDATE pesajes_lotes "
                "SET estado = 'ANULADO', id_registro_bruto = NULL, "
                "    motivo_anulacion = ?, updated_at = ? "
                "WHERE id_pesaje_lote = ?",
                (motivo.strip(), ahora(), id_lote),
            )

    @classmethod
    def anular_todos(cls, id_pesaje, motivo, conexion=None):
        """Anula todos los lotes de un ingreso (conserva sus capturas)."""

        with transaccion(conexion) as cx:
            cx.execute(
                "UPDATE pesajes_lotes "
                "SET estado = 'ANULADO', motivo_anulacion = ?, updated_at = ? "
                "WHERE id_pesaje = ? AND estado <> 'ANULADO'",
                (motivo, ahora(), id_pesaje),
            )


# ======================================================================
# CAPTURAS FÍSICAS  (tabla pesajes_registros)
# Cuelgan del ingreso, no del lote: una misma captura puede ser la tara de
# un lote y el bruto del siguiente. SOLO inserción (la BD lo impide con
# triggers). Un error se corrige con anular().
# ======================================================================
class PesajeRegistroModel(ModeloBase):

    tabla = "pesajes_registros"
    pk = "id_registro"
    uuid_col = "uuid_registro"
    con_timestamps = False
    columnas = ("id_pesaje", "secuencia", "peso", "fecha_hora")

    @classmethod
    def registrar(cls, id_pesaje, peso, conexion=None):
        """Inserta una captura con la siguiente secuencia. Devuelve su ID."""

        with transaccion(conexion) as cx:
            secuencia = cx.execute(
                "SELECT COALESCE(MAX(secuencia), 0) + 1 "
                "FROM pesajes_registros WHERE id_pesaje = ?",
                (id_pesaje,),
            ).fetchone()[0]

            return cls.add(
                {
                    "id_pesaje": id_pesaje,
                    "secuencia": secuencia,
                    "peso": peso,
                    "fecha_hora": ahora(),
                },
                cx,
            )

    @classmethod
    def by_pesaje(cls, id_pesaje, incluir_anuladas=False, conexion=None):

        sql = "SELECT * FROM pesajes_registros WHERE id_pesaje = ?"

        if not incluir_anuladas:
            sql += " AND anulado = 0"

        with lectura(conexion) as cx:
            filas = cx.execute(sql + " ORDER BY secuencia", (id_pesaje,)).fetchall()

        return [dict(f) for f in filas]

    @classmethod
    def ultimo_valido(cls, id_pesaje, conexion=None):
        """Última captura no anulada del ingreso (o None)."""

        with lectura(conexion) as cx:
            fila = cx.execute(
                "SELECT * FROM pesajes_registros "
                "WHERE id_pesaje = ? AND anulado = 0 "
                "ORDER BY secuencia DESC LIMIT 1",
                (id_pesaje,),
            ).fetchone()

        return cls._a_dict(fila)

    @classmethod
    def ultimo_sin_bruto(cls, id_pesaje, conexion=None):
        """
        Última captura válida, siempre que todavía no sea el bruto de
        ningún lote. Es la que toma un lote declarado DESPUÉS de capturar.
        """

        with lectura(conexion) as cx:
            fila = cx.execute(
                """
                SELECT r.* FROM pesajes_registros r
                WHERE r.id_pesaje = ? AND r.anulado = 0
                  AND r.secuencia = (SELECT MAX(secuencia)
                                       FROM pesajes_registros
                                      WHERE id_pesaje = ? AND anulado = 0)
                  AND NOT EXISTS (SELECT 1 FROM pesajes_lotes l
                                   WHERE l.id_registro_bruto = r.id_registro
                                     AND l.estado <> 'ANULADO')
                """,
                (id_pesaje, id_pesaje),
            ).fetchone()

        return cls._a_dict(fila)

    @classmethod
    def contar_huerfanas(cls, id_pesaje, conexion=None):
        """Capturas válidas que ningún lote activo usa (ni como bruto ni tara)."""

        with lectura(conexion) as cx:
            return cx.execute(
                """
                SELECT COUNT(*) FROM pesajes_registros r
                WHERE r.id_pesaje = ? AND r.anulado = 0
                  AND r.id_registro NOT IN (
                      SELECT id_registro_bruto FROM pesajes_lotes
                       WHERE id_pesaje = ? AND estado <> 'ANULADO'
                         AND id_registro_bruto IS NOT NULL
                      UNION
                      SELECT id_registro_tara FROM pesajes_lotes
                       WHERE id_pesaje = ? AND estado <> 'ANULADO'
                         AND id_registro_tara IS NOT NULL)
                """,
                (id_pesaje, id_pesaje, id_pesaje),
            ).fetchone()[0]

    @classmethod
    def anular(cls, id_registro, motivo, conexion=None):
        """Marca la captura como anulada (no la borra)."""

        if not motivo or not motivo.strip():
            raise ReglaNegocioError("Indique el motivo de la anulación.")

        with transaccion(conexion) as cx:
            cx.execute(
                "UPDATE pesajes_registros SET anulado = 1, motivo_anulacion = ? "
                "WHERE id_registro = ?",
                (motivo.strip(), id_registro),
            )

    # Solo inserción
    @classmethod
    def update_by_id(cls, *args, **kwargs):
        raise ReglaNegocioError(
            "Las capturas no se modifican. Anule la captura y capture de nuevo."
        )

    @classmethod
    def delete_by_id(cls, *args, **kwargs):
        raise ReglaNegocioError("Las capturas no se borran, solo se anulan.")


# ======================================================================
# CORRELATIVO DE LOTES  (tabla configuracion_lotes, una sola fila)
# Formato: <último dígito del año><mes>-<correlativo>  ->  "610-2245"
# ======================================================================
class ConfiguracionLotesModel:

    @classmethod
    def get(cls, conexion=None):
        """Devuelve la configuración como dict, o None si no existe."""

        with lectura(conexion) as cx:
            fila = cx.execute(
                "SELECT * FROM configuracion_lotes WHERE id_configuracion = 1"
            ).fetchone()

        return dict(fila) if fila else None

    @classmethod
    def guardar(cls, correlativo, conexion=None):
        """Crea o actualiza el próximo correlativo."""

        if not isinstance(correlativo, int) or correlativo <= 0:
            raise ReglaNegocioError(
                "El correlativo debe ser un número entero mayor que cero."
            )

        t = ahora()

        with transaccion(conexion) as cx:
            cx.execute(
                """
                INSERT INTO configuracion_lotes
                    (id_configuracion, proximo_correlativo, created_at, updated_at)
                VALUES (1, ?, ?, ?)
                ON CONFLICT(id_configuracion) DO UPDATE SET
                    proximo_correlativo = excluded.proximo_correlativo,
                    updated_at = excluded.updated_at
                """,
                (correlativo, t, t),
            )

    @staticmethod
    def prefijo(fecha=None):

        fecha = fecha or datetime.now()

        return f"{str(fecha.year)[-1]}{fecha.month:02d}"

    @classmethod
    def proximo_lote(cls, conexion=None):
        """Texto del próximo lote (o None si no hay configuración)."""

        config = cls.get(conexion)

        if config is None:
            return None

        return f"{cls.prefijo()}-{config['proximo_correlativo']}"

    @classmethod
    def consumir_correlativo(cls, conexion):
        """
        Avanza el correlativo en 1. Debe llamarse dentro de la MISMA
        transacción que crea el lote (por eso la conexión es obligatoria).
        """

        config = cls.get(conexion)

        if config is None:
            raise ReglaNegocioError(
                "No se ha configurado ningún correlativo para los lotes."
            )

        actual = config["proximo_correlativo"]

        conexion.execute(
            "UPDATE configuracion_lotes "
            "SET proximo_correlativo = ?, updated_at = ? "
            "WHERE id_configuracion = 1",
            (actual + 1, ahora()),
        )

        return actual
