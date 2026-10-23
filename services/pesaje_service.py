"""
Operaciones de negocio sobre ingresos, lotes y capturas.

Cada método público es UNA transacción: o se guarda todo o no se guarda nada.
Los métodos lanzan ReglaNegocioError (mensaje listo para mostrar al usuario)
cuando se viola una regla.

Cadena de pesadas (N lotes = N+1 capturas):
    la tara de un lote es el bruto del siguiente.
"""

import math
import json
import re
from datetime import datetime

from database.conexion import ahora, transaccion
from models.base import ReglaNegocioError
from models.pesajes import (
    ConfiguracionLotesModel,
    PesajeLoteModel,
    PesajeModel,
    PesajeRegistroModel,
)


class PesajeService:

    # AUXILIARES
    @classmethod
    def _ingreso_abierto(cls, id_pesaje, cx):
        """Devuelve el ingreso si existe y está EN_PROCESO; si no, error."""

        ingreso = PesajeModel.by_id(id_pesaje, cx)

        if ingreso is None:
            raise ReglaNegocioError("El ingreso no existe.")

        if ingreso["estado"] != "EN_PROCESO":
            raise ReglaNegocioError(
                f"El ingreso {ingreso['ticket']} está {ingreso['estado']}."
            )

        return ingreso

    @staticmethod
    def _normalizar_peso(peso):

        try:
            valor = float(peso)
        except (TypeError, ValueError):
            raise ReglaNegocioError("El peso no es un número válido.")

        if not math.isfinite(valor) or valor <= 0:
            raise ReglaNegocioError("El peso debe ser mayor que cero.")

        entero = round(valor)

        if abs(valor - entero) > 1e-6:
            raise ReglaNegocioError(
                f"La balanza envió un peso con decimales ({peso}). "
                f"Las capturas se guardan en kg enteros."
            )

        return int(entero)

    @staticmethod
    def _peso_evento_tx(cx, id_registro):
        fila = cx.execute(
            """SELECT r.peso,
                      (SELECT c.peso_nuevo
                         FROM historial_correcciones_pesaje c
                        WHERE c.id_registro = r.id_registro
                        ORDER BY c.id_correccion DESC LIMIT 1) AS corregido
                 FROM pesajes_registros r WHERE r.id_registro = ?""",
            (id_registro,),
        ).fetchone()
        if fila is None:
            return None
        return fila["corregido"] if fila["corregido"] is not None else fila["peso"]

    @classmethod
    def _preparar_correccion_tx(cls, cx, id_pesaje, id_lote, tipo, peso_nuevo):
        tipo = (tipo or "").upper()
        if tipo not in ("BRUTO", "TARA"):
            raise ReglaNegocioError("Seleccione una celda de peso bruto o tara.")

        ingreso = cx.execute(
            "SELECT * FROM pesajes WHERE id_pesaje = ?", (id_pesaje,)
        ).fetchone()
        if ingreso is None:
            raise ReglaNegocioError("El ingreso ya no existe.")
        if ingreso["estado"] == "ANULADO":
            raise ReglaNegocioError("No se pueden corregir pesajes de un ingreso anulado.")
        if ingreso["sincronizado"]:
            raise ReglaNegocioError(
                "El ingreso ya fue sincronizado; no se pueden corregir sus pesajes."
            )

        lote = cx.execute(
            "SELECT * FROM pesajes_lotes WHERE id_pesaje_lote = ? AND id_pesaje = ?",
            (id_lote, id_pesaje),
        ).fetchone()
        if lote is None or lote["estado"] == "ANULADO":
            raise ReglaNegocioError("El lote seleccionado no existe o está anulado.")

        primero = cx.execute(
            "SELECT MIN(orden) FROM pesajes_lotes "
            "WHERE id_pesaje = ? AND estado <> 'ANULADO'",
            (id_pesaje,),
        ).fetchone()[0]
        if tipo == "BRUTO" and lote["orden"] != primero:
            raise ReglaNegocioError(
                "Para corregir un bruto, seleccione la primera pesada del primer lote."
            )
        campo_id = "id_registro_bruto" if tipo == "BRUTO" else "id_registro_tara"
        id_registro = lote[campo_id]
        if id_registro is None:
            raise ReglaNegocioError("La celda seleccionada todavía no tiene una captura.")

        registro = cx.execute(
            "SELECT * FROM pesajes_registros WHERE id_registro = ? AND id_pesaje = ?",
            (id_registro, id_pesaje),
        ).fetchone()
        if registro is None or registro["anulado"]:
            raise ReglaNegocioError("La captura seleccionada ya no está vigente.")

        peso_anterior = cls._peso_evento_tx(cx, id_registro)
        if peso_nuevo == peso_anterior:
            raise ReglaNegocioError("El peso nuevo es igual al peso actual.")

        def peso_sql(alias):
            return f"COALESCE((SELECT c.peso_nuevo FROM historial_correcciones_pesaje c " \
                   f"WHERE c.id_registro = {alias}.id_registro " \
                   f"ORDER BY c.id_correccion DESC LIMIT 1), {alias}.peso)"

        anterior = cx.execute(
            f"SELECT {peso_sql('r')} AS peso FROM pesajes_registros r "
            "WHERE r.id_pesaje = ? AND r.anulado = 0 AND r.secuencia < ? "
            "ORDER BY r.secuencia DESC LIMIT 1",
            (id_pesaje, registro["secuencia"]),
        ).fetchone()
        siguiente = cx.execute(
            f"SELECT {peso_sql('r')} AS peso FROM pesajes_registros r "
            "WHERE r.id_pesaje = ? AND r.anulado = 0 AND r.secuencia > ? "
            "ORDER BY r.secuencia LIMIT 1",
            (id_pesaje, registro["secuencia"]),
        ).fetchone()
        if anterior and peso_nuevo >= anterior["peso"]:
            raise ReglaNegocioError(
                f"El nuevo peso debe ser menor que la captura anterior ({anterior['peso']} kg)."
            )
        if siguiente and peso_nuevo <= siguiente["peso"]:
            raise ReglaNegocioError(
                f"El nuevo peso debe ser mayor que la captura siguiente ({siguiente['peso']} kg)."
            )

        referencias = cx.execute(
            """SELECT id_pesaje_lote, lote, id_registro_bruto, id_registro_tara
                 FROM pesajes_lotes
                WHERE id_pesaje = ? AND estado <> 'ANULADO'
                  AND (id_registro_bruto = ? OR id_registro_tara = ?)
                ORDER BY orden""",
            (id_pesaje, id_registro, id_registro),
        ).fetchall()
        afectados = []
        for referencia in referencias:
            bruto_anterior = (
                cls._peso_evento_tx(cx, referencia["id_registro_bruto"])
                if referencia["id_registro_bruto"] is not None else None
            )
            tara_anterior = (
                cls._peso_evento_tx(cx, referencia["id_registro_tara"])
                if referencia["id_registro_tara"] is not None else None
            )
            bruto_nuevo = (
                peso_nuevo if referencia["id_registro_bruto"] == id_registro
                else bruto_anterior
            )
            tara_nueva = (
                peso_nuevo if referencia["id_registro_tara"] == id_registro
                else tara_anterior
            )
            if bruto_nuevo is not None and tara_nueva is not None and bruto_nuevo <= tara_nueva:
                raise ReglaNegocioError(
                    f"La corrección dejaría el bruto del lote {referencia['lote']} "
                    "menor o igual que su tara."
                )
            afectados.append({
                "lote": referencia["lote"],
                "neto_anterior": (
                    bruto_anterior - tara_anterior
                    if bruto_anterior is not None and tara_anterior is not None else None
                ),
                "neto_nuevo": (
                    bruto_nuevo - tara_nueva
                    if bruto_nuevo is not None and tara_nueva is not None else None
                ),
            })

        return {
            "id_registro": id_registro,
            "tipo": tipo,
            "lote_seleccionado": lote["lote"],
            "peso_anterior": peso_anterior,
            "peso_nuevo": peso_nuevo,
            "secuencia": registro["secuencia"],
            "afectados": afectados,
        }

    @staticmethod
    def _normalizar_fecha_hora(valor):
        texto = (valor or "").strip()
        for formato in ("%Y-%m-%d %I:%M:%S %p", "%Y-%m-%d %I:%M %p",
                        "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
                        "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M"):
            try:
                return datetime.strptime(texto, formato).strftime("%Y-%m-%dT%H:%M:%S")
            except ValueError:
                pass
        raise ReglaNegocioError(
            "Use el formato AAAA-MM-DD HH:MM:SS para la fecha y hora."
        )

    @staticmethod
    def formatear_fecha_hora(valor):
        if not valor:
            return ""
        try:
            return datetime.fromisoformat(str(valor).replace("Z", "+00:00")).strftime(
                "%Y-%m-%d %I:%M:%S %p"
            )
        except ValueError:
            return str(valor).replace("T", " ")

    @staticmethod
    def _fecha_evento_tx(cx, id_registro):
        fila = cx.execute(
            """SELECT r.fecha_hora,
                      (SELECT c.fecha_hora_nueva
                         FROM historial_correcciones_pesaje c
                        WHERE c.id_registro = r.id_registro
                          AND c.fecha_hora_nueva IS NOT NULL
                        ORDER BY c.id_correccion DESC LIMIT 1) AS corregida
                 FROM pesajes_registros r WHERE r.id_registro = ?""",
            (id_registro,),
        ).fetchone()
        if fila is None:
            return None
        return fila["corregida"] or fila["fecha_hora"]

    @classmethod
    def _preparar_correccion_fecha_tx(cls, cx, id_pesaje, id_lote, tipo, fecha_nueva):
        tipo = (tipo or "").upper()
        if tipo not in ("BRUTO", "TARA"):
            raise ReglaNegocioError("Seleccione una celda de fecha/hora válida.")
        ingreso = cx.execute(
            "SELECT * FROM pesajes WHERE id_pesaje = ?", (id_pesaje,)
        ).fetchone()
        if ingreso is None or ingreso["estado"] == "ANULADO":
            raise ReglaNegocioError("El ingreso no existe o está anulado.")
        if ingreso["sincronizado"]:
            raise ReglaNegocioError(
                "El ingreso ya fue sincronizado; no se pueden corregir sus pesajes."
            )
        lote = cx.execute(
            "SELECT * FROM pesajes_lotes WHERE id_pesaje_lote = ? AND id_pesaje = ?",
            (id_lote, id_pesaje),
        ).fetchone()
        if lote is None or lote["estado"] == "ANULADO":
            raise ReglaNegocioError("El lote seleccionado no existe o está anulado.")
        campo_id = "id_registro_bruto" if tipo == "BRUTO" else "id_registro_tara"
        id_registro = lote[campo_id]
        if id_registro is None:
            raise ReglaNegocioError("La celda seleccionada todavía no tiene una captura.")
        registro = cx.execute(
            "SELECT * FROM pesajes_registros WHERE id_registro = ? AND id_pesaje = ?",
            (id_registro, id_pesaje),
        ).fetchone()
        if registro is None or registro["anulado"]:
            raise ReglaNegocioError("La captura seleccionada ya no está vigente.")

        fecha_anterior = cls._fecha_evento_tx(cx, id_registro)
        if fecha_nueva == fecha_anterior:
            raise ReglaNegocioError("La fecha y hora nuevas son iguales a las actuales.")
        anteriores = cx.execute(
            "SELECT id_registro FROM pesajes_registros "
            "WHERE id_pesaje = ? AND anulado = 0 AND secuencia < ? "
            "ORDER BY secuencia DESC LIMIT 1",
            (id_pesaje, registro["secuencia"]),
        ).fetchone()
        siguientes = cx.execute(
            "SELECT id_registro FROM pesajes_registros "
            "WHERE id_pesaje = ? AND anulado = 0 AND secuencia > ? "
            "ORDER BY secuencia LIMIT 1",
            (id_pesaje, registro["secuencia"]),
        ).fetchone()
        if anteriores and fecha_nueva < cls._fecha_evento_tx(cx, anteriores["id_registro"]):
            raise ReglaNegocioError("La fecha debe ser posterior a la captura anterior.")
        if siguientes and fecha_nueva > cls._fecha_evento_tx(cx, siguientes["id_registro"]):
            raise ReglaNegocioError("La fecha debe ser anterior a la captura siguiente.")

        referencias = cx.execute(
            """SELECT lote FROM pesajes_lotes
                WHERE id_pesaje = ? AND estado <> 'ANULADO'
                  AND (id_registro_bruto = ? OR id_registro_tara = ?)
                ORDER BY orden""",
            (id_pesaje, id_registro, id_registro),
        ).fetchall()
        peso_actual = cls._peso_evento_tx(cx, id_registro)
        return {
            "id_registro": id_registro, "tipo": tipo,
            "lote_seleccionado": lote["lote"],
            "fecha_hora_anterior": fecha_anterior,
            "fecha_hora_nueva": fecha_nueva,
            "peso_actual": peso_actual,
            "secuencia": registro["secuencia"],
            "afectados": [
                {"lote": ref["lote"], "fecha_anterior": fecha_anterior,
                 "fecha_nueva": fecha_nueva} for ref in referencias
            ],
        }

    @classmethod
    def previsualizar_correccion_fecha(cls, id_pesaje, id_lote, tipo, fecha_hora):
        fecha_nueva = cls._normalizar_fecha_hora(fecha_hora)
        with transaccion() as cx:
            return cls._preparar_correccion_fecha_tx(
                cx, id_pesaje, id_lote, tipo, fecha_nueva
            )

    @classmethod
    def corregir_fecha_pesaje(cls, id_pesaje, id_lote, tipo, fecha_hora, motivo):
        motivo = (motivo or "").strip()
        if not motivo:
            raise ReglaNegocioError("Indique el motivo de la corrección.")
        fecha_nueva = cls._normalizar_fecha_hora(fecha_hora)
        with transaccion() as cx:
            datos = cls._preparar_correccion_fecha_tx(
                cx, id_pesaje, id_lote, tipo, fecha_nueva
            )
            cx.execute(
                """INSERT INTO historial_correcciones_pesaje
                   (id_pesaje, id_registro, id_pesaje_lote, tipo,
                    peso_anterior, peso_nuevo, fecha_hora_anterior,
                    fecha_hora_nueva, motivo, fecha_hora)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (id_pesaje, datos["id_registro"], id_lote, datos["tipo"],
                 datos["peso_actual"], datos["peso_actual"],
                 datos["fecha_hora_anterior"], datos["fecha_hora_nueva"],
                 motivo, ahora()),
            )
        return datos

    @classmethod
    def previsualizar_correccion_pesaje(cls, id_pesaje, id_lote, tipo, peso):
        peso_nuevo = cls._normalizar_peso(peso)
        with transaccion() as cx:
            return cls._preparar_correccion_tx(
                cx, id_pesaje, id_lote, tipo, peso_nuevo
            )

    @classmethod
    def corregir_pesaje(cls, id_pesaje, id_lote, tipo, peso, motivo):
        motivo = (motivo or "").strip()
        if not motivo:
            raise ReglaNegocioError("Indique el motivo de la corrección.")
        peso_nuevo = cls._normalizar_peso(peso)
        with transaccion() as cx:
            datos = cls._preparar_correccion_tx(
                cx, id_pesaje, id_lote, tipo, peso_nuevo
            )
            cx.execute(
                """INSERT INTO historial_correcciones_pesaje
                   (id_pesaje, id_registro, id_pesaje_lote, tipo,
                    peso_anterior, peso_nuevo, motivo, fecha_hora)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (id_pesaje, datos["id_registro"], id_lote, datos["tipo"],
                 datos["peso_anterior"], peso_nuevo, motivo, ahora()),
            )
        return datos

    # INGRESO
    @classmethod
    def crear_ingreso(cls, equipo=None, datos=None):
        """
        Botón NUEVO: reserva el ticket creando el ingreso.
        `datos` puede traer id_vehiculo, id_carreta, id_conductor,
        id_transportista.
        """

        with transaccion() as cx:
            campos = PesajeModel.solo_columnas(datos or {}, excluir=("ticket",))
            campos["ticket"] = PesajeModel.siguiente_ticket(cx)
            campos["equipo"] = equipo

            id_pesaje = PesajeModel.add(campos, cx)

        return PesajeModel.by_id(id_pesaje)

    @classmethod
    def actualizar_ingreso(cls, id_pesaje, datos):
        """Actualiza vehículo, carreta, conductor y transportista."""

        campos = PesajeModel.solo_columnas(datos, excluir=("ticket",))

        return PesajeModel.update_by_id(id_pesaje, campos)

    # LOTES
    @classmethod
    def _agregar_lote_tx(cls, cx, id_pesaje, datos):
        """
        Agrega un lote DENTRO de una transacción ya abierta (cx).
        Devuelve el id del lote. No hace commit.
        """

        cls._ingreso_abierto(id_pesaje, cx)

        campos = PesajeLoteModel.solo_columnas(datos, excluir=("id_pesaje", "orden"))

        lote = (campos.get("lote") or "").strip()
        propuesto = ConfiguracionLotesModel.proximo_lote(cx)

        if not lote:
            if propuesto is None:
                raise ReglaNegocioError(
                    "Configure el correlativo de lotes o escriba el lote."
                )
            lote = propuesto

        if lote == propuesto:
            ConfiguracionLotesModel.consumir_correlativo(cx)

        campos["lote"] = lote
        campos["id_pesaje"] = id_pesaje
        campos["orden"] = PesajeLoteModel.siguiente_orden(id_pesaje, cx)

        id_lote = PesajeLoteModel.add(campos, cx)

        # Si ya hay una captura que ningún lote usa como bruto, la toma.
        pendiente = PesajeRegistroModel.ultimo_sin_bruto(id_pesaje, cx)

        if pendiente:
            PesajeLoteModel.asignar_bruto(id_lote, pendiente["id_registro"], cx)

        return id_lote

    @classmethod
    def agregar_lote(cls, id_pesaje, datos):
        """
        Botón AGREGAR LOTE: crea el lote SIN pesar.

        - Si no se indica `lote`, se usa el próximo del correlativo.
        - El correlativo se consume solo si el lote es el propuesto.
        - Si ya hay una captura sin lote, la toma como su bruto.
        """

        with transaccion() as cx:
            id_lote = cls._agregar_lote_tx(cx, id_pesaje, datos)

        return PesajeLoteModel.by_id(id_lote)

    @classmethod
    def actualizar_lote(cls, id_lote, datos):
        """Actualiza datos del lote; en CONFIRMADO solo campos comerciales.

        Las capturas, referencias bruto/tara, estado y datos de operación no
        se aceptan desde este método. Un ingreso ANULADO es inmutable.
        """
        campos_permitidos_confirmado = {
            "id_proveedor", "guia_proveedor", "guia_transportista",
            "id_concesion", "procedencia", "producto", "observacion",
            "tipo_carga", "cantidad_sacos", "priorizar_analisis",
        }
        with transaccion() as cx:
            lote = PesajeLoteModel.by_id(id_lote, cx)
            if lote is None:
                raise ReglaNegocioError("El lote no existe.")
            ingreso = PesajeModel.by_id(lote["id_pesaje"], cx)
            if ingreso is None:
                raise ReglaNegocioError("El ingreso del lote no existe.")
            campos = PesajeLoteModel.solo_columnas(
                datos, excluir=("id_pesaje", "orden",
                                "id_registro_bruto", "id_registro_tara",
                                "estado", "motivo_anulacion")
            )
            if ingreso["estado"] == "ANULADO":
                raise ReglaNegocioError("No se pueden modificar lotes de un ingreso anulado.")
            if ingreso["estado"] == "CONFIRMADO":
                no_permitidos = set(campos) - campos_permitidos_confirmado
                if no_permitidos:
                    raise ReglaNegocioError(
                        "Un ingreso confirmado solo permite editar datos comerciales del lote."
                    )
            elif ingreso["estado"] != "EN_PROCESO":
                raise ReglaNegocioError("El estado del ingreso no permite modificar el lote.")
            return PesajeLoteModel.update_by_id(id_lote, campos, cx)

    @classmethod
    def anular_lote(cls, id_lote, motivo):

        with transaccion() as cx:
            lote = PesajeLoteModel.by_id(id_lote, cx)

            if lote is None:
                raise ReglaNegocioError("El lote no existe.")

            cls._ingreso_abierto(lote["id_pesaje"], cx)
            PesajeLoteModel.anular(id_lote, motivo, cx)

    # ELIMINACIÓN CON HISTORIAL
    @classmethod
    def eliminar_lote(cls, id_lote, motivo="Eliminación solicitada por el usuario"):
        """Elimina un lote operativo, conserva snapshot y respeta la cadena.

        Regla de la cadena: no se permite eliminar un lote cuyo BRUTO sea la
        TARA de un lote anterior del mismo ticket. En ese caso se debe eliminar
        primero el lote anterior. Una captura que siga siendo usada como bruto
        por un lote posterior no se anula.
        """
        with transaccion() as cx:
            lote = cx.execute(
                "SELECT * FROM pesajes_lotes WHERE id_pesaje_lote = ?",
                (id_lote,),
            ).fetchone()
            if lote is None:
                raise ReglaNegocioError("El lote seleccionado ya no existe.")
            lote = dict(lote)
            ingreso = cx.execute(
                "SELECT * FROM pesajes WHERE id_pesaje = ?", (lote["id_pesaje"],)
            ).fetchone()
            if ingreso is None:
                raise ReglaNegocioError("No se encontró el ticket del lote.")
            if ingreso["estado"] == "ANULADO":
                raise ReglaNegocioError("No se pueden eliminar lotes de un ticket anulado.")

            # Si el bruto del lote seleccionado se usó como tara de otro lote,
            # el lote anterior debe retirarse primero.
            bloqueador = None
            if lote.get("id_registro_bruto") is not None:
                fila = cx.execute(
                    """SELECT lote FROM pesajes_lotes
                       WHERE id_pesaje = ?
                         AND id_pesaje_lote <> ?
                         AND id_registro_tara = ?
                         AND estado <> 'ANULADO'
                       ORDER BY orden LIMIT 1""",
                    (lote["id_pesaje"], id_lote, lote["id_registro_bruto"]),
                ).fetchone()
                if fila:
                    bloqueador = fila["lote"]
            if bloqueador:
                raise ReglaNegocioError(
                    f"No se puede eliminar el lote {lote['lote']}. "
                    f"Primero debe eliminar el lote anterior {bloqueador}, "
                    "porque comparte una captura de pesaje con él."
                )

            ids_registros = sorted({
                int(x) for x in (lote.get("id_registro_bruto"), lote.get("id_registro_tara"))
                if x is not None
            })
            registros = []
            if ids_registros:
                placeholders = ",".join("?" for _ in ids_registros)
                registros = [dict(r) for r in cx.execute(
                    f"SELECT * FROM pesajes_registros WHERE id_registro IN ({placeholders})",
                    ids_registros,
                ).fetchall()]

            # El historial contiene el lote y las capturas tal como estaban.
            snapshot = {"lote": lote, "ticket": dict(ingreso), "capturas": registros}
            cx.execute(
                """INSERT INTO historial_eliminaciones
                   (tipo_entidad, id_entidad_original, ticket, lote, motivo, datos_json)
                   VALUES ('LOTE', ?, ?, ?, ?, ?)""",
                (id_lote, ingreso["ticket"], lote["lote"], motivo, json.dumps(snapshot, ensure_ascii=False, default=str)),
            )

            cx.execute("DELETE FROM pesajes_lotes WHERE id_pesaje_lote = ?", (id_lote,))

            # Una captura se marca anulada solo cuando ya no la referencia ningún lote.
            for id_registro in ids_registros:
                usada = cx.execute(
                    """SELECT 1 FROM pesajes_lotes
                       WHERE id_registro_bruto = ? OR id_registro_tara = ? LIMIT 1""",
                    (id_registro, id_registro),
                ).fetchone()
                if not usada:
                    cx.execute(
                        """UPDATE pesajes_registros
                           SET anulado = 1, motivo_anulacion = ?
                           WHERE id_registro = ? AND anulado = 0""",
                        (f"Captura archivada al eliminar el lote {lote['lote']}", id_registro),
                    )

            # Recuperar correlativo solo si este lote es el último usado.
            match = re.search(r"-(\d+)$", str(lote["lote"]))
            config = ConfiguracionLotesModel.get(cx)
            if match and config:
                correlativo = int(match.group(1))
                todos_lotes = [r[0] for r in cx.execute(
                    "SELECT lote FROM pesajes_lotes UNION ALL "
                    "SELECT lote FROM historial_eliminaciones WHERE tipo_entidad = 'LOTE'"
                ).fetchall() if r[0]]
                sufijos = []
                for texto in todos_lotes:
                    m = re.search(r"-(\d+)$", str(texto))
                    if m:
                        sufijos.append(int(m.group(1)))
                if config["proximo_correlativo"] == correlativo + 1 and max(sufijos or [correlativo]) == correlativo:
                    cx.execute(
                        "UPDATE configuracion_lotes SET proximo_correlativo = ?, updated_at = ? WHERE id_configuracion = 1",
                        (correlativo, __import__("datetime").datetime.now().isoformat(timespec="seconds")),
                    )

            return {"lote": lote["lote"], "ticket": ingreso["ticket"], "correlativo_recuperado": bool(match and config and config["proximo_correlativo"] == correlativo + 1 and max(sufijos or [correlativo]) == correlativo)}

    @classmethod
    def eliminar_ticket_vacio(cls, id_pesaje, motivo="Eliminación de ticket vacío"):
        """Elimina un ticket solo si no tiene lotes ni capturas asociadas."""
        with transaccion() as cx:
            ingreso = cx.execute("SELECT * FROM pesajes WHERE id_pesaje = ?", (id_pesaje,)).fetchone()
            if ingreso is None:
                raise ReglaNegocioError("El ticket ya no existe.")
            ticket = dict(ingreso)
            lotes = cx.execute("SELECT COUNT(*) FROM pesajes_lotes WHERE id_pesaje = ?", (id_pesaje,)).fetchone()[0]
            capturas = cx.execute("SELECT COUNT(*) FROM pesajes_registros WHERE id_pesaje = ?", (id_pesaje,)).fetchone()[0]
            if lotes or capturas:
                raise ReglaNegocioError(
                    f"No se puede eliminar el ticket {ticket['ticket']}: "
                    f"todavía tiene {lotes} lote(s) y {capturas} captura(s). "
                    "El ticket debe estar completamente vacío."
                )
            cx.execute(
                """INSERT INTO historial_eliminaciones
                   (tipo_entidad, id_entidad_original, ticket, lote, motivo, datos_json)
                   VALUES ('TICKET', ?, ?, NULL, ?, ?)""",
                (id_pesaje, ticket["ticket"], motivo, json.dumps({"ticket": ticket}, ensure_ascii=False, default=str)),
            )
            cx.execute("DELETE FROM pesajes WHERE id_pesaje = ?", (id_pesaje,))
            return ticket["ticket"]

    # CAPTURAS
    @classmethod
    def _capturar_tx(cls, cx, id_pesaje, peso):
        """
        Registra una captura DENTRO de una transacción ya abierta (cx).
        `peso` ya viene normalizado (entero). No hace commit.

        La cadena decide el destino, nunca el operador:
        1. si hay un lote abierto (bruto sin tara) -> es su TARA y lo completa.
        2. si hay un siguiente lote sin bruto      -> es su BRUTO.
        Una misma captura puede cumplir los dos papeles a la vez.
        """

        ingreso = cls._ingreso_abierto(id_pesaje, cx)

        if ingreso["id_vehiculo"] is None:
            raise ReglaNegocioError(
                "Seleccione la placa del vehículo antes de capturar."
            )

        anterior = PesajeRegistroModel.ultimo_valido(id_pesaje, cx)

        if anterior and peso >= anterior["peso"]:
            raise ReglaNegocioError(
                f"El peso ({peso} kg) debe ser menor que la captura "
                f"anterior ({anterior['peso']} kg)."
            )

        abierto = PesajeLoteModel.abierto(id_pesaje, cx)
        siguiente = PesajeLoteModel.siguiente_sin_bruto(id_pesaje, cx)

        # Evita capturas sin destino (p. ej. un doble clic al terminar).
        if abierto is None and siguiente is None:
            if PesajeLoteModel.by_pesaje(id_pesaje, conexion=cx):
                raise ReglaNegocioError(
                    "Todos los lotes ya tienen sus pesadas. Use AGREGAR LOTE "
                    "si hay otro lote, o presione GUARDAR."
                )
            if anterior:
                raise ReglaNegocioError(
                    "Agregue el lote antes de la siguiente captura."
                )

        id_registro = PesajeRegistroModel.registrar(id_pesaje, peso, cx)
        registro = PesajeRegistroModel.by_id(id_registro, cx)

        resultado = {
            "id_registro": id_registro,
            "secuencia": registro["secuencia"],
            "peso": peso,
            "tara_de": None,
            "bruto_de": None,
            "neto": None,
            "lote_creado": None,
        }

        if abierto:
            peso_bruto = cls._peso_evento_tx(cx, abierto["id_registro_bruto"])

            PesajeLoteModel.asignar_tara(abierto["id_pesaje_lote"], id_registro, cx)

            resultado["tara_de"] = abierto["lote"]
            resultado["neto"] = peso_bruto - peso

        if siguiente:
            PesajeLoteModel.asignar_bruto(siguiente["id_pesaje_lote"], id_registro, cx)

            resultado["bruto_de"] = siguiente["lote"]

        return resultado

    @classmethod
    def registrar_captura(cls, id_pesaje, peso):
        """
        Captura de bajo nivel: solo asigna la captura según la cadena.
        Para el botón CAPTURAR PESO use capturar().
        """

        peso = cls._normalizar_peso(peso)

        with transaccion() as cx:
            return cls._capturar_tx(cx, id_pesaje, peso)

    @classmethod
    def capturar(cls, id_pesaje, peso, datos_lote=None):
        """Captura el peso siguiendo la cadena de lotes ya reservados.

        Reglas:
        - Si no existen lotes ni capturas, crea el primer lote con datos_lote.
        - Si existe un lote sin bruto, la captura será su BRUTO.
        - Si existe un lote abierto y otro reservado sin bruto, la captura
          será TARA del primero y BRUTO del siguiente.
        - Si solo queda un lote abierto, la captura será únicamente su TARA.
        - Nunca crea un lote adicional automáticamente durante una captura
          intermedia. Para crear otro lote se debe usar AGREGAR LOTE.

        Toda la operación se ejecuta en una única transacción.
        """
        peso = cls._normalizar_peso(peso)

        with transaccion() as cx:
            cls._ingreso_abierto(id_pesaje, cx)

            abierto = PesajeLoteModel.abierto(id_pesaje, cx)
            siguiente = PesajeLoteModel.siguiente_sin_bruto(id_pesaje, cx)
            sin_capturas = PesajeRegistroModel.ultimo_valido(id_pesaje, cx) is None
            lote_creado = None

            # Solo crear automáticamente el primer lote cuando la operación
            # está vacía. No crear lotes nuevos por una captura intermedia.
            if abierto is None and siguiente is None and sin_capturas:
                if datos_lote is None:
                    raise ReglaNegocioError(
                        "Complete los datos del primer lote antes de capturar."
                    )
                cls._validar_datos_lote_nuevo(datos_lote)
                id_lote = cls._agregar_lote_tx(cx, id_pesaje, datos_lote)
                lote_creado = PesajeLoteModel.by_id(id_lote, cx)["lote"]

            # Si no hay lotes pendientes de recibir una captura, _capturar_tx
            # mostrará el mensaje apropiado. No inferimos que el operador
            # quiere crear otro lote a partir de los campos del formulario.
            resultado = cls._capturar_tx(cx, id_pesaje, peso)
            resultado["lote_creado"] = lote_creado

        return resultado

    @staticmethod
    def _validar_datos_lote_nuevo(datos_lote):
        """Valida los datos mínimos antes de reservar un lote automáticamente."""
        if not datos_lote.get("id_proveedor"):
            raise ReglaNegocioError(
                "Seleccione el proveedor desde la lista antes de crear el lote."
            )

        tipo_carga = datos_lote.get("tipo_carga")
        if tipo_carga not in ("SACO", "GRANEL"):
            raise ReglaNegocioError("Seleccione si la carga es SACO o GRANEL.")

        if tipo_carga == "SACO":
            sacos = datos_lote.get("cantidad_sacos")
            if isinstance(sacos, bool) or not isinstance(sacos, int) or sacos <= 0:
                raise ReglaNegocioError(
                    "Un lote en SACOS debe tener una cantidad de sacos mayor que 0."
                )

    @classmethod
    def anular_ultima_captura(cls, id_pesaje, motivo):
        """
        Corrige un error de captura: anula SOLO la última captura válida
        y deja los lotes como estaban antes de ella.
        """

        with transaccion() as cx:
            cls._ingreso_abierto(id_pesaje, cx)

            ultimo = PesajeRegistroModel.ultimo_valido(id_pesaje, cx)

            if ultimo is None:
                raise ReglaNegocioError("El ingreso no tiene capturas.")

            PesajeRegistroModel.anular(ultimo["id_registro"], motivo, cx)
            PesajeLoteModel.liberar_registro(id_pesaje, ultimo["id_registro"], cx)

        return ultimo

    # CONFIRMAR / ANULAR / REABRIR INGRESO
    @classmethod
    def confirmar_ingreso(cls, id_pesaje):
        """
        Botón GUARDAR: confirma el ingreso. Exige vehículo, al menos un lote,
        ningún lote PENDIENTE y ninguna captura sin lote.
        """

        with transaccion() as cx:
            ingreso = cls._ingreso_abierto(id_pesaje, cx)

            if ingreso["id_vehiculo"] is None:
                raise ReglaNegocioError("Falta seleccionar el vehículo.")

            lotes = PesajeLoteModel.by_pesaje(id_pesaje, conexion=cx)

            if not lotes:
                raise ReglaNegocioError("El ingreso no tiene lotes.")

            pendientes = [l["lote"] for l in lotes if l["estado"] == "PENDIENTE"]

            if pendientes:
                raise ReglaNegocioError(
                    "Faltan pesadas en los lotes: " + ", ".join(pendientes) + "."
                )

            if PesajeRegistroModel.contar_huerfanas(id_pesaje, cx):
                raise ReglaNegocioError(
                    "Hay capturas que no pertenecen a ningún lote. "
                    "Anule la última captura o agregue el lote que falta."
                )

            PesajeModel.cambiar_estado(id_pesaje, "CONFIRMADO", conexion=cx)

        return PesajeModel.by_id(id_pesaje)

    @classmethod
    def reabrir_ingreso(cls, id_pesaje):
        """Vuelve un ingreso CONFIRMADO a EN_PROCESO (si no se sincronizó)."""

        with transaccion() as cx:
            ingreso = PesajeModel.by_id(id_pesaje, cx)

            if ingreso is None:
                raise ReglaNegocioError("El ingreso no existe.")

            if ingreso["estado"] != "CONFIRMADO":
                raise ReglaNegocioError("Solo se reabre un ingreso CONFIRMADO.")

            if ingreso["sincronizado"]:
                raise ReglaNegocioError(
                    "El ingreso ya se sincronizó con el sistema comercial."
                )

            PesajeModel.cambiar_estado(id_pesaje, "EN_PROCESO", conexion=cx)

        return PesajeModel.by_id(id_pesaje)

    @classmethod
    def anular_ingreso(cls, id_pesaje, motivo):
        """Anula el ingreso completo (y todos sus lotes). Exige motivo."""

        if not motivo or not motivo.strip():
            raise ReglaNegocioError("Indique el motivo de la anulación.")

        with transaccion() as cx:
            ingreso = PesajeModel.by_id(id_pesaje, cx)

            if ingreso is None:
                raise ReglaNegocioError("El ingreso no existe.")

            if ingreso["estado"] == "ANULADO":
                raise ReglaNegocioError("El ingreso ya está anulado.")

            if ingreso["sincronizado"]:
                raise ReglaNegocioError(
                    "El ingreso ya se sincronizó: no se puede anular aquí."
                )

            PesajeLoteModel.anular_todos(id_pesaje, motivo.strip(), cx)
            PesajeModel.cambiar_estado(
                id_pesaje, "ANULADO", motivo.strip(), conexion=cx
            )

        return PesajeModel.by_id(id_pesaje)

    # CONSULTAS PARA LA INTERFAZ
    @classmethod
    def ingresos_pendientes(cls):
        return PesajeModel.pendientes()

    @classmethod
    def todos_los_ingresos(cls):
        return PesajeModel.todos()

    @classmethod
    def lotes_detalle(cls, id_pesaje, incluir_anulados=False, descendente=False):

        return PesajeLoteModel.detalle(id_pesaje, incluir_anulados, descendente)

    @classmethod
    def preparar_datos_ticket(cls, id_pesaje_lote):
        """
        Prepara los datos del ticket PDF para un solo lote.

        Solo permite imprimir lotes COMPLETADOS que tengan bruto, tara,
        fechas y peso neto. La vista SQL es la fuente de los pesos.
        """
        lote = PesajeLoteModel.detalle_por_id(id_pesaje_lote)

        if lote is None:
            raise ReglaNegocioError("El lote seleccionado ya no existe.")

        if lote.get("estado") == "ANULADO":
            raise ReglaNegocioError("No se puede imprimir un lote anulado.")

        campos_pesada = (
            lote.get("peso_bruto"),
            lote.get("peso_tara"),
            lote.get("peso_neto"),
            lote.get("fecha_bruto"),
            lote.get("fecha_tara"),
        )
        if lote.get("estado") != "COMPLETADO" or any(v is None for v in campos_pesada):
            raise ReglaNegocioError(
                "No se puede imprimir este lote porque todavía no tiene las dos "
                "pesadas completas (bruto y tara)."
            )

        def texto(valor):
            return "" if valor is None else str(valor).strip()

        def fecha_hora(valor):
            """Convierte fecha ISO de SQLite a fecha y hora legibles."""
            if not valor:
                return "", ""
            from datetime import datetime

            try:
                dt = datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
                return dt.strftime("%d/%m/%Y"), dt.strftime("%H:%M:%S")
            except ValueError:
                partes = str(valor).replace("T", " ").split(" ", 1)
                return (partes[0] if partes else "", partes[1] if len(partes) > 1 else "")

        def peso(valor):
            # Los pesos de la balanza se guardan en kg enteros.
            numero = float(valor)
            return str(int(numero)) if numero.is_integer() else f"{numero:g}"

        fecha1, hora1 = fecha_hora(lote.get("fecha_bruto"))
        fecha2, hora2 = fecha_hora(lote.get("fecha_tara"))

        tipo_carga = texto(lote.get("tipo_carga")).upper()
        sacos = (
            texto(lote.get("cantidad_sacos"))
            if tipo_carga == "SACO"
            else "GRANEL"
        )

        return {
            # Metadato utilizado para nombrar el PDF generado.
            "ticket": texto(lote.get("ticket")),
            "empresa": "MINERA MH S.A.C.",
            "titulo": "TICKET DE PESAJE",
            "direccion": "EL BOSQUE JS SECTOR PAMPA LA AGUADA CHALA CARAVELI AREQUIPA",
            "placa": texto(lote.get("placa")),
            "carreta": texto(lote.get("carreta")),
            "lote": texto(lote.get("lote")),
            "chofer": texto(lote.get("chofer")),
            "licencia": texto(lote.get("brevete")),
            "transportista": texto(lote.get("transportista")),
            "transportista_ruc": texto(lote.get("ruc_transportista")),
            "proveedor": texto(lote.get("proveedor")),
            "proveedor_ruc": texto(lote.get("ruc_proveedor")),
            "concesion": texto(lote.get("concesion")),
            "codigo": texto(lote.get("codigo_concesion")),
            "procedencia": texto(lote.get("procedencia")),
            "producto": texto(lote.get("producto")),
            "n_sacos": sacos,
            "gr_remit": texto(lote.get("guia_proveedor")),
            "gr_transp": texto(lote.get("guia_transportista")),
            "observacion": texto(lote.get("observacion")),
            "advertencia": "",
            "fecha1": fecha1,
            "hora1": hora1,
            "fecha2": fecha2,
            "hora2": hora2,
            "peso_bruto": peso(lote.get("peso_bruto")),
            "peso_tara": peso(lote.get("peso_tara")),
            "peso_neto": peso(lote.get("peso_neto")),
            "nota_pie": "",
        }

    @classmethod
    def preparar_datos_declaracion_jurada(cls, id_pesaje, proveedor):
        """Prepara una DJ con todos los lotes completados de un proveedor."""
        proveedor = (proveedor or "").strip()
        lotes_proveedor = [
            lote for lote in PesajeLoteModel.detalle(id_pesaje, descendente=False)
            if str(lote.get("proveedor") or "").strip() == proveedor
        ]
        if not lotes_proveedor:
            raise ReglaNegocioError("El proveedor no tiene lotes en esta operación.")

        incompletos = [
            lote["lote"] for lote in lotes_proveedor
            if lote.get("estado") != "COMPLETADO"
            or any(lote.get(campo) is None for campo in
                   ("peso_bruto", "peso_tara", "peso_neto", "fecha_bruto", "fecha_tara"))
        ]
        if incompletos:
            raise ReglaNegocioError(
                "Complete las pesadas antes de generar la DJ. Lotes pendientes: "
                + ", ".join(incompletos)
            )

        def texto(valor):
            return "" if valor is None else str(valor).strip()

        def valores_unicos(campo):
            vistos = set()
            salida = []
            for lote in lotes_proveedor:
                valor = texto(lote.get(campo))
                clave = valor.casefold()
                if valor and clave not in vistos:
                    salida.append(valor)
                    vistos.add(clave)
            return ", ".join(salida)

        primer_lote = lotes_proveedor[0]
        brevete = texto(primer_lote.get("brevete"))
        dni_chofer = (
            brevete[1:]
            if brevete[:1].isalpha()
            else texto(primer_lote.get("dni_chofer"))
        )
        detalle = []
        for lote in lotes_proveedor:
            detalle.append({
                "lote": texto(lote.get("lote")),
                "concesion": texto(lote.get("concesion")),
                "procedencia": texto(lote.get("procedencia")),
                "guia_proveedor": texto(lote.get("guia_proveedor")),
                "guia_transportista": texto(lote.get("guia_transportista")),
                "tipo_carga": texto(lote.get("tipo_carga")),
                "cantidad_sacos": lote.get("cantidad_sacos"),
                "fecha_bruto": texto(lote.get("fecha_bruto")),
                "fecha_tara": texto(lote.get("fecha_tara")),
                "peso_bruto": lote.get("peso_bruto"),
                "peso_tara": lote.get("peso_tara"),
                "peso_neto": lote.get("peso_neto"),
            })

        return {
            "ticket": texto(primer_lote.get("ticket")),
            "fecha_emision": ahora(),
            "proveedor": proveedor,
            "proveedor_ruc": texto(primer_lote.get("ruc_proveedor")),
            "transportista": texto(primer_lote.get("transportista")),
            "transportista_ruc": texto(primer_lote.get("ruc_transportista")),
            "chofer": texto(primer_lote.get("chofer")),
            "dni_chofer": dni_chofer,
            "brevete": brevete,
            "domicilio_dni": texto(primer_lote.get("domicilio_chofer")),
            "placa": texto(primer_lote.get("placa")),
            "carreta": texto(primer_lote.get("carreta")),
            "vehiculo_placas": " / ".join(
                valor for valor in (
                    texto(primer_lote.get("placa")),
                    texto(primer_lote.get("carreta")),
                ) if valor
            ),
            "concesion": valores_unicos("concesion"),
            "codigo_concesion": valores_unicos("codigo_concesion"),
            "procedencia": valores_unicos("procedencia"),
            "guias_proveedor": valores_unicos("guia_proveedor"),
            "direccion_empresa": (
                "EL BOSQUE JS SECTOR PAMPA LA AGUADA, distrito de Chala, "
                "provincia de Caravelí, departamento de Arequipa"
            ),
            "lotes": detalle,
            "total_neto": sum(float(lote["peso_neto"]) for lote in detalle),
            "total_tmh": sum(float(lote["peso_neto"]) for lote in detalle) / 1000,
            "total_sacos": sum(
                int(lote["cantidad_sacos"] or 0) for lote in detalle
                if lote["tipo_carga"].upper() == "SACO"
            ),
        }

    @classmethod
    def filas_para_tabla(cls, id_pesaje, descendente=False):
        """
        Tuplas de 8 valores para view.cargar_pesajes():
        (lote, sacos, fecha_hora_1, peso_1, fecha_hora_2, peso_2, neto, estado)
        1ª pesada = bruto, 2ª pesada = tara.
        """

        def fecha(valor):
            return cls.formatear_fecha_hora(valor)

        def texto(valor):
            return "" if valor is None else valor

        filas = []

        for l in PesajeLoteModel.detalle(id_pesaje, descendente=descendente):

            sacos = l["cantidad_sacos"] if l["tipo_carga"] == "SACO" else "GRANEL"

            filas.append(
                (
                    l["lote"],
                    sacos,
                    fecha(l["fecha_bruto"]),
                    texto(l["peso_bruto"]),
                    fecha(l["fecha_tara"]),
                    texto(l["peso_tara"]),
                    texto(l["peso_neto"]),
                    l["estado"],
                )
            )

        return filas
