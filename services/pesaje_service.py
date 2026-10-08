"""
Operaciones de negocio sobre ingresos, lotes y capturas.

Cada método público es UNA transacción: o se guarda todo o no se guarda nada.
Los métodos lanzan ReglaNegocioError (mensaje listo para mostrar al usuario)
cuando se viola una regla.

Cadena de pesadas (N lotes = N+1 capturas):
    la tara de un lote es el bruto del siguiente.
"""

import math

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
    def agregar_lote(cls, id_pesaje, datos):
        """
        Agrega un lote al ingreso.

        - Si no se indica `lote`, se usa el próximo del correlativo.
        - El correlativo se consume solo si el lote es el propuesto.
        - Si ya hay una captura sin lote, la toma como su bruto.
        """

        with transaccion() as cx:
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

            pendiente = PesajeRegistroModel.ultimo_sin_bruto(id_pesaje, cx)

            if pendiente:
                PesajeLoteModel.asignar_bruto(id_lote, pendiente["id_registro"], cx)

        return PesajeLoteModel.by_id(id_lote)

    @classmethod
    def actualizar_lote(cls, id_lote, datos):

        campos = PesajeLoteModel.solo_columnas(datos, excluir=("id_pesaje", "orden"))

        with transaccion() as cx:
            lote = PesajeLoteModel.by_id(id_lote, cx)

            if lote is None:
                raise ReglaNegocioError("El lote no existe.")

            cls._ingreso_abierto(lote["id_pesaje"], cx)

            return PesajeLoteModel.update_by_id(id_lote, campos, cx)

    @classmethod
    def anular_lote(cls, id_lote, motivo):

        with transaccion() as cx:
            lote = PesajeLoteModel.by_id(id_lote, cx)

            if lote is None:
                raise ReglaNegocioError("El lote no existe.")

            cls._ingreso_abierto(lote["id_pesaje"], cx)
            PesajeLoteModel.anular(id_lote, motivo, cx)

    # CAPTURAS
    @classmethod
    def registrar_captura(cls, id_pesaje, peso):
        """
        Botón CAPTURAR PESO. Guarda la captura al instante y la asigna:

        1. si hay un lote abierto (bruto sin tara) -> es su TARA y lo completa.
        2. si hay un siguiente lote sin bruto      -> es su BRUTO.
        3. si el ingreso aún no tiene lotes (primera captura) -> queda
           guardada y la tomará el primer lote que se agregue.
        Si todos los lotes ya están completos, se rechaza la captura.

        Devuelve un dict con lo que pasó (para mostrar en la interfaz).
        """

        peso = cls._normalizar_peso(peso)

        with transaccion() as cx:
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
                        "Todos los lotes ya tienen sus pesadas. Agregue otro "
                        "lote o presione GUARDAR."
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
    def lotes_detalle(cls, id_pesaje, incluir_anulados=False, descendente=False):

        return PesajeLoteModel.detalle(id_pesaje, incluir_anulados, descendente)

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
