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

from database.conexion import transaccion
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
                datos, excluir=("id_pesaje", "orden", "lote",
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
            bruto = PesajeRegistroModel.by_id(abierto["id_registro_bruto"], cx)

            PesajeLoteModel.asignar_tara(abierto["id_pesaje_lote"], id_registro, cx)

            resultado["tara_de"] = abierto["lote"]
            resultado["neto"] = bruto["peso"] - peso

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
        """Captura el peso y, cuando corresponde, crea el siguiente lote en una transacción.

        Reglas:
        - Primera captura sin lotes: crea el primer lote y lo asigna como BRUTO.
        - Si ya existe un siguiente lote reservado, se respeta; no se crea otro.
        - Si hay un lote abierto (espera TARA) y no existe siguiente lote, puede
          crearse automáticamente el próximo lote. La captura queda como TARA
          del lote abierto y BRUTO del nuevo lote.
        - No se crea automáticamente si hay capturas huérfanas sin asignar.
        - Si todos los lotes están completos, no se crea otro lote con una pesada
          adicional; se debe usar AGREGAR LOTE o GUARDAR.

        Si una validación falla, la transacción revierte lote, captura y correlativo.
        """

        peso = cls._normalizar_peso(peso)

        with transaccion() as cx:
            cls._ingreso_abierto(id_pesaje, cx)

            abierto = PesajeLoteModel.abierto(id_pesaje, cx)
            siguiente = PesajeLoteModel.siguiente_sin_bruto(id_pesaje, cx)
            sin_capturas = PesajeRegistroModel.ultimo_valido(id_pesaje, cx) is None
            lote_creado = None

            # Primera captura: debe existir el primer lote antes de guardar el peso.
            if abierto is None and siguiente is None and sin_capturas:
                if datos_lote is None:
                    raise ReglaNegocioError(
                        "Complete los datos del primer lote antes de capturar."
                    )
                cls._validar_datos_lote_nuevo(datos_lote)
                id_lote = cls._agregar_lote_tx(cx, id_pesaje, datos_lote)
                lote_creado = PesajeLoteModel.by_id(id_lote, cx)["lote"]

            # La captura intermedia también será BRUTO del siguiente lote,
            # pero solo si no había un lote ya reservado para recibirla.
            elif abierto is not None and siguiente is None:
                if datos_lote is None:
                    raise ReglaNegocioError(
                        "No hay un siguiente lote reservado. Complete los datos "
                        "del nuevo lote para crearlo automáticamente, o use AGREGAR LOTE."
                    )

                huerfanas = PesajeRegistroModel.contar_huerfanas(id_pesaje, cx)
                if huerfanas:
                    raise ReglaNegocioError(
                        "No se puede crear automáticamente el siguiente lote porque "
                        f"hay {huerfanas} pesada(s) sin asignar. Revise los pesajes "
                        "pendientes antes de continuar."
                    )

                cls._validar_datos_lote_nuevo(datos_lote)
                id_lote = cls._agregar_lote_tx(cx, id_pesaje, datos_lote)
                lote_creado = PesajeLoteModel.by_id(id_lote, cx)["lote"]

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
    def filas_para_tabla(cls, id_pesaje, descendente=False):
        """
        Tuplas de 8 valores para view.cargar_pesajes():
        (lote, sacos, fecha_hora_1, peso_1, fecha_hora_2, peso_2, neto, estado)
        1ª pesada = bruto, 2ª pesada = tara.
        """

        def fecha(valor):
            return valor.replace("T", " ") if valor else ""

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
