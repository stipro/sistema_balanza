from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QMessageBox

import serial
import serial.tools.list_ports

from services.serial_balanza import SerialBalanza
from services.serial_display import SerialDisplay
from utils.parser_peso import ParserPeso

from models.base import ReglaNegocioError
from models.maestros import (
    VehiculoModel,
    CarretaModel,
    ConductorModel,
    ProveedorModel,
    TransportistaModel,
    ConcesionModel,
)
from models.pesajes import (
    ConfiguracionLotesModel,
    PesajeLoteModel,
    PesajeModel,
)
from services.pesaje_service import PesajeService
from services.reporte_pdf_service import ReportePdfService
from views.pendientes_view import PendientesView
from views.pesajes_view import PesajesView

from config.settings import (
    BAUDRATE_BALANZA_DEFAULT,
    BAUDRATE_DISPLAY_DEFAULT,
    INTERVALO_LECTURA_MS,
    TIMEOUT_INICIO_MS,
    SERIAL_TIMEOUT,
    PUERTO_BALANZA_DEFAULT,
    PUERTO_DISPLAY_DEFAULT,
)


class BalanzaController:

    def __init__(self, view):

        self.view = view

        # ==========================================================
        # SERIAL
        # ==========================================================

        self.balanza = None
        self.display = None

        self.balanza_comunicando = False
        self.esperando_balanza = False

        # Último peso válido recibido de la balanza.
        # Se utiliza cuando el usuario presiona "Capturar peso".
        self.ultimo_peso = None

        # ==========================================================
        # INGRESO ACTUAL
        # ==========================================================

        self.ingreso_actual = None
        self._mapa_lotes = {}
        self._lote_en_edicion = None
        # {
        #     "id_pesaje": int,
        #     "ticket": int
        # }

        # ==========================================================
        # CARGAR DATOS INICIALES
        # ==========================================================

        self.cargar_maestros()
        self._verificar_pendientes()

        # ==========================================================
        # TIMER DE LECTURA DE BALANZA
        # ==========================================================

        self.timer = QTimer()
        self.timer.setInterval(INTERVALO_LECTURA_MS)
        self.timer.timeout.connect(self.procesar_balanza)

        # ==========================================================
        # TIMER DE ESPERA INICIAL
        # ==========================================================

        self.timer_inicio = QTimer()
        self.timer_inicio.setSingleShot(True)
        self.timer_inicio.setInterval(TIMEOUT_INICIO_MS)
        self.timer_inicio.timeout.connect(self.error_inicio)

        # ==========================================================
        # EVENTOS DE LA VIEW
        # ==========================================================

        self.view.btn_iniciar.clicked.connect(self.iniciar)
        self.view.btn_detener.clicked.connect(self.detener)
        self.view.cerrando.connect(self.cerrar)

        # Ingreso
        self.view.btn_nuevo.clicked.connect(self.nuevo_registro)
        self.view.btn_agregar_lote.clicked.connect(self.agregar_lote)
        self.view.btn_capturar.clicked.connect(self.capturar_peso)
        self.view.btn_guardar.clicked.connect(self.guardar_ingreso)
        self.view.btn_imprimir.clicked.connect(self.imprimir_lote)
        self.view.btn_modificar.clicked.connect(self.modificar_lote_seleccionado)
        self.view.btn_pendientes.clicked.connect(self.mostrar_pesajes)
        # Al seleccionar un lote, cargar sus datos comerciales en el formulario.
        self.view.tabla_pesajes.itemSelectionChanged.connect(
            self.cargar_lote_seleccionado
        )

        # Configuración de lotes
        self.view.configuracion_lotes.btn_guardar.clicked.connect(
            self.guardar_configuracion_lotes
        )

        # Configuración serial
        self.view.configuracion.btn_actualizar.clicked.connect(self.detectar_puertos)

        self.view.act_configuracion.triggered.connect(self.view.mostrar_configuracion)

        self.view.act_configuracion_lotes.triggered.connect(
            self.mostrar_configuracion_lotes
        )

        self.view.act_actualizar_puertos.triggered.connect(self.detectar_puertos)

        # Maestros
        self.view.btn_actualizar_maestros.clicked.connect(self.actualizar_maestros)

        # ==========================================================
        # DETECTAR PUERTOS AL INICIAR
        # ==========================================================

        self.detectar_puertos()

    # ==================================================================
    # MAESTROS
    # ==================================================================

    def cargar_maestros(self):
        """
        Carga los maestros activos desde SQLite y los entrega a la View.

        Los maestros se manejan mediante sus modelos.
        No se consulta directamente la base de datos desde el controller.
        """

        self.view.cargar_maestros(
            VehiculoModel.activos(),
            CarretaModel.activos(),
            ConductorModel.activos(),
            ProveedorModel.activos(),
            TransportistaModel.activos(),
            ConcesionModel.activos(),
        )

    def actualizar_maestros(self):
        """
        Recarga los maestros desde SQLite.
        """

        try:
            self.cargar_maestros()
            self.log("[OK] Maestros recargados desde SQLite.")

        except Exception as e:
            self.log(f"[ERROR MAESTROS] {e}")

            QMessageBox.warning(
                self.view,
                "Actualizar maestros",
                f"No se pudieron actualizar los maestros.\n\n{e}",
            )

    # ==================================================================
    # CONFIGURACIÓN DE LOTES
    # ==================================================================

    def guardar_configuracion_lotes(self):
        """
        Guarda el próximo correlativo de lotes.
        """

        correlativo = self.view.configuracion_lotes.spin_correlativo.value()

        try:

            ConfiguracionLotesModel.guardar(correlativo)

            self.view.configuracion_lotes.ocultar_aviso()

            QMessageBox.information(
                self.view,
                "Configuración de lotes",
                (
                    "Configuración guardada correctamente.\n\n"
                    f"Próximo lote: "
                    f"{ConfiguracionLotesModel.proximo_lote()}"
                ),
            )

            self.view.configuracion_lotes.accept()

        except ReglaNegocioError as e:

            QMessageBox.warning(
                self.view,
                "Configuración de lotes",
                str(e),
            )

    def mostrar_configuracion_lotes(self):
        """
        Abre la ventana de configuración de lotes.
        """

        config = ConfiguracionLotesModel.get()

        if config is None:

            self.view.configuracion_lotes.mostrar_sin_configuracion()

        else:

            self.view.configuracion_lotes.cargar_correlativo(
                config["proximo_correlativo"]
            )

        self.view.configuracion_lotes.exec()

    # INGRESO
    def nuevo_registro(self):
        """
        Inicia un nuevo ingreso EN_PROCESO.

        Si todavía no existe configuración de lotes,
        obliga a configurarla antes de crear el ticket.
        """

        # ==============================================================
        # 1. Verificar configuración de lotes
        # ==============================================================

        config = ConfiguracionLotesModel.get()

        if config is None:

            QMessageBox.information(
                self.view,
                "Configuración requerida",
                (
                    "No se ha configurado el correlativo de lotes.\n\n"
                    "Configure el correlativo inicial antes de iniciar "
                    "un nuevo pesaje."
                ),
            )

            # Abrir automáticamente la configuración de lotes.
            self.mostrar_configuracion_lotes()

            # Verificar nuevamente después de cerrar la ventana.
            config = ConfiguracionLotesModel.get()

            # El usuario canceló o no guardó la configuración.
            if config is None:
                return

        # ==============================================================
        # 2. Limpiar ingreso vacío anterior
        # ==============================================================

        self._limpiar_ingreso_vacio()

        # ==============================================================
        # 3. Crear nuevo ingreso
        # ==============================================================

        try:

            ingreso = PesajeService.crear_ingreso(equipo="PC-1")

            self.ingreso_actual = {
                "id_pesaje": ingreso["id_pesaje"],
                "ticket": ingreso["ticket"],
            }

            print("[DEBUG] ingreso_actual:", self.ingreso_actual)

            # Limpiar peso temporal anterior.
            self.ultimo_peso = None

            # ==========================================================
            # 4. Obtener el próximo lote
            # ==========================================================

            proximo_lote = ConfiguracionLotesModel.proximo_lote()

            # ==========================================================
            # 5. Preparar la interfaz
            # ==========================================================

            self.view.preparar_nuevo_registro(
                ingreso["ticket"],
                proximo_lote,
            )

            self.log(f"[NUEVO] Ticket {ingreso['ticket']} creado " f"(pendiente).")

        except ReglaNegocioError as e:

            QMessageBox.warning(
                self.view,
                "Nuevo ingreso",
                str(e),
            )

    def _limpiar_ingreso_vacio(self):
        """
        Elimina únicamente el ingreso actual si todavía está vacío.

        Si ya tiene lotes/capturas, PesajeModel no permitirá eliminarlo
        y quedará como ingreso pendiente.
        """

        if not self.ingreso_actual:
            return

        try:

            PesajeModel.delete_by_id(self.ingreso_actual["id_pesaje"])

            self.log(
                f"[INFO] Ticket " f"{self.ingreso_actual['ticket']} vacío eliminado."
            )

        except ReglaNegocioError:

            # Tenía información asociada.
            # Debe conservarse como pendiente.
            pass

        self.ingreso_actual = None

    def _sincronizar_datos_generales(self):
        """
        Lee los datos seleccionados en la View y los guarda
        en la tabla pesajes.
        """

        if not self.ingreso_actual:
            return

        datos = {
            "id_vehiculo": self.view.txt_placa.id_actual(),
            "id_carreta": self.view.txt_carreta.id_actual(),
            "id_conductor": (self.view.conductor_seleccionado or {}).get(
                "id_conductor"
            ),
            "id_transportista": (self.view.transportista_seleccionado or {}).get(
                "id_transportista"
            ),
        }

        PesajeService.actualizar_ingreso(
            self.ingreso_actual["id_pesaje"],
            datos,
        )

    # ==================================================================
    # LOTES
    # ==================================================================

    def agregar_lote(self):
        """Botón AGREGAR LOTE: crea el lote SIN peso (flujo del diagrama)."""

        if not self.ingreso_actual:
            QMessageBox.warning(self.view, "Lote", "Presione NUEVO primero.")
            return

        datos = self.view.obtener_datos_lote()

        if datos["id_proveedor"] is None:

            QMessageBox.warning(
                self.view,
                "Proveedor",
                "Seleccione el proveedor desde la lista desplegable "
                "(no escriba uno nuevo a mano).",
            )
            return

        try:
            self._sincronizar_datos_generales()

            lote = PesajeService.agregar_lote(self.ingreso_actual["id_pesaje"], datos)

            self.log(
                f"[LOTE] {lote['lote']} agregado al ticket "
                f"{self.ingreso_actual['ticket']} (sin peso)."
            )

            self.view.limpiar_campos_lote()
            self.view.mostrar_proximo_lote(ConfiguracionLotesModel.proximo_lote())
            self._refrescar_lotes()

        except ReglaNegocioError as e:
            QMessageBox.warning(self.view, "Agregar lote", str(e))

    # ==================================================================
    # CAPTURA DE PESO
    # ==================================================================

    def capturar_peso(self):
        """
        Botón CAPTURAR PESO.

        La cadena de pesadas decide automáticamente el destino:

        - Primera captura:
            BRUTO del primer lote.

        - Capturas siguientes:
            TARA del lote anterior
            +
            BRUTO del siguiente lote.

        - Última captura:
            TARA del último lote.

        El usuario no decide manualmente si una captura es BRUTO o TARA.
        """

        if not self.ingreso_actual:
            QMessageBox.warning(
                self.view,
                "Sin operación",
                "Primero debe iniciar una operación (NUEVO).",
            )
            return

        if not self.balanza_comunicando or self.ultimo_peso is None:
            QMessageBox.warning(
                self.view,
                "Balanza",
                "No hay peso válido de la balanza.",
            )
            return

        try:
            # Sincronizar datos generales del ingreso
            self._sincronizar_datos_generales()

            # El Service decide si necesita crear un lote nuevo.
            # Si ya existe un lote reservado, estos datos se ignoran.
            datos_lote = self.view.obtener_datos_lote()

            # El Service decide automáticamente:
            #
            # 1. Primera pesada  -> BRUTO lote 1
            # 2. Siguiente       -> TARA lote anterior
            #                       + BRUTO lote siguiente
            # 3. Última           -> TARA último lote
            resultado = PesajeService.capturar(
                self.ingreso_actual["id_pesaje"],
                self.ultimo_peso,
                datos_lote=datos_lote,
            )

            self._log_captura(resultado)

            # Limpiar datos del formulario para el siguiente lote
            self.view.limpiar_campos_lote()

            self.view.mostrar_proximo_lote(ConfiguracionLotesModel.proximo_lote())

            # Actualizar tabla
            self._refrescar_lotes()

        except ReglaNegocioError as e:
            QMessageBox.warning(
                self.view,
                "Capturar peso",
                str(e),
            )

    def _capturar_nuevo_lote_con_peso(self):
        """
        Crea el lote con los datos del formulario y le asigna
        esta captura como BRUTO.
        """

        datos = self.view.obtener_datos_lote()

        if datos["id_proveedor"] is None:
            raise ReglaNegocioError(
                "Seleccione el proveedor desde la lista antes de capturar."
            )

        self._sincronizar_datos_generales()

        lote = PesajeService.agregar_lote(self.ingreso_actual["id_pesaje"], datos)

        r = PesajeService.registrar_captura_para_lote(
            lote["id_pesaje_lote"], self.ultimo_peso
        )

        self._log_captura(r)

        self.view.limpiar_campos_lote()
        self.view.mostrar_proximo_lote(ConfiguracionLotesModel.proximo_lote())
        self._refrescar_lotes()

    def _capturar_peso_lote_existente(self, lote_texto):
        """
        Captura dirigida al lote de la fila seleccionada (o al lote
        abierto de la cadena). El service decide si es bruto o tara.
        """

        id_lote = self._mapa_lotes.get(lote_texto)

        if id_lote is None:
            raise ReglaNegocioError(
                "La fila seleccionada ya no existe. Actualice la tabla."
            )

        self._sincronizar_datos_generales()

        r = PesajeService.registrar_captura_para_lote(id_lote, self.ultimo_peso)

        self._log_captura(r)

        self.view.tabla_pesajes.clearSelection()
        self._refrescar_lotes()

    def _log_captura(self, r):
        """Log común de ambas ramas."""

        detalle = f"[CAPTURA #{r['secuencia']}] {r['peso']} kg"

        if r["bruto_de"]:
            detalle += f" -> BRUTO de {r['bruto_de']}"

        if r["tara_de"]:
            detalle += f" -> TARA de {r['tara_de']}"

        if r["neto"] is not None:
            detalle += f" | NETO: {r['neto']} kg"

        self.log(detalle)

    # ==================================================================
    # GUARDAR / CONFIRMAR
    # ==================================================================

    def guardar_ingreso(self):
        """
        Confirma definitivamente el ingreso.

        Las reglas reales de validación están en PesajeService.
        """

        if not self.ingreso_actual:

            QMessageBox.warning(
                self.view,
                "Guardar",
                "No hay ingreso activo.",
            )

            return

        filas = PesajeService.filas_para_tabla(
            self.ingreso_actual["id_pesaje"],
            descendente=True,
        )

        completos = sum(1 for fila in filas if fila[7] == "COMPLETO")

        respuesta = QMessageBox.question(
            self.view,
            "Confirmar ingreso",
            (
                f"¿Confirmar el ticket "
                f"{self.ingreso_actual['ticket']}?\n\n"
                f"Lotes: {len(filas)} | "
                f"Completos: {completos}\n\n"
                "Esta acción bloquea las capturas "
                "de este ingreso."
            ),
            (QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No),
        )

        if respuesta != QMessageBox.StandardButton.Yes:
            return

        try:

            # Guardar nuevamente los datos generales
            # antes de confirmar.
            self._sincronizar_datos_generales()

            ingreso = PesajeService.confirmar_ingreso(self.ingreso_actual["id_pesaje"])

            QMessageBox.information(
                self.view,
                "Ingreso confirmado",
                (f"Ticket {ingreso['ticket']} " "confirmado correctamente."),
            )

            self.log(f"[GUARDAR] Ticket " f"{ingreso['ticket']} CONFIRMADO.")

            self.view.estado_operacion("completo")

            self.ingreso_actual = None
            self.ultimo_peso = None

            self.view.bloquear_formulario(True)

        except ReglaNegocioError as e:

            QMessageBox.warning(
                self.view,
                "No se puede guardar",
                str(e),
            )

    # ==================================================================
    # PESAJES PENDIENTES
    # ==================================================================

    def _verificar_pendientes(self):
        """
        Al iniciar el programa verifica si quedaron ingresos
        EN_PROCESO de una sesión anterior.
        """

        try:

            pendientes = PesajeService.ingresos_pendientes()

            if pendientes:

                self.log(
                    f"[INFO] Hay {len(pendientes)} "
                    "ingreso(s) pendiente(s). "
                    "Use el botón PESAJES PENDIENTES "
                    "para continuarlos."
                )

        except Exception as e:

            self.log(f"[ERROR] No se pudieron verificar " f"los pendientes: {e}")

    def cargar_lote_seleccionado(self):
        """Muestra en el formulario los datos del lote seleccionado.

        La selección solo consulta/carga datos; guardar cambios sigue siendo
        responsabilidad del botón MODIFICAR y de PesajeService.
        """
        if not self.ingreso_actual:
            return

        lote_texto = self.view.obtener_fila_lote_seleccionada()
        if not lote_texto:
            return

        id_lote = self._mapa_lotes.get(lote_texto)
        if not id_lote:
            return

        try:
            lote = PesajeLoteModel.detalle_por_id(id_lote)
            if not lote:
                return

            # No recargar el mismo lote repetidamente si el cambio de selección
            # fue provocado por un refresco de la tabla.
            self.view.cargar_datos_lote(lote)

            # Si no estamos en edición, el botón conserva su función de entrar
            # al modo de modificación para el lote seleccionado.
            if self._lote_en_edicion != id_lote:
                self.view.btn_modificar.setText("✎  MODIFICAR")
        except Exception as e:
            self.log(f"[ERROR] No se pudieron cargar los datos del lote {lote_texto}: {e}")

    def modificar_lote_seleccionado(self):
        """Carga y guarda datos comerciales del lote seleccionado.

        En ingresos CONFIRMADO solo permite datos del lote; el Service vuelve
        a validar las reglas para impedir modificaciones a las capturas.
        """
        if not self.ingreso_actual:
            QMessageBox.information(self.view, "Modificar lote", "Primero abra un ingreso desde PESAJES.")
            return

        estado = PesajeModel.by_id(self.ingreso_actual["id_pesaje"])
        if not estado:
            QMessageBox.warning(self.view, "Modificar lote", "El ingreso ya no existe.")
            return
        estado_ingreso = estado.get("estado")
        if estado_ingreso == "ANULADO":
            QMessageBox.information(self.view, "Modificar lote", "Un ingreso anulado es de solo lectura.")
            return

        lote_texto = self.view.obtener_fila_lote_seleccionada()
        if not lote_texto or lote_texto not in self._mapa_lotes:
            QMessageBox.information(self.view, "Modificar lote", "Seleccione un lote en la tabla.")
            return
        id_lote = self._mapa_lotes[lote_texto]

        # Primer clic: cargar el lote seleccionado en el formulario.
        if self._lote_en_edicion != id_lote:
            lote = PesajeLoteModel.detalle_por_id(id_lote)
            if not lote:
                QMessageBox.warning(self.view, "Modificar lote", "No se encontró el lote seleccionado.")
                return
            self.view.cargar_datos_lote(lote)
            self._lote_en_edicion = id_lote
            self.view.btn_modificar.setText("💾  GUARDAR CAMBIOS")
            for campo in (self.view.txt_proveedor, self.view.txt_ruc_proveedor,
                          self.view.txt_guia_proveedor, self.view.txt_guia_transportista,
                          self.view.txt_concesion, self.view.txt_codigo,
                          self.view.txt_procedencia, self.view.txt_producto,
                          self.view.txt_observacion, self.view.cmb_tipo_carga,
                          self.view.txt_sacos):
                campo.setEnabled(True)
            return

        # Segundo clic: persistir solo los campos comerciales permitidos.
        try:
            datos = self.view.obtener_datos_lote()
            PesajeService.actualizar_lote(id_lote, datos)
            self._lote_en_edicion = None
            self.view.btn_modificar.setText("✎  MODIFICAR")
            self.view.aplicar_modo_ingreso(estado_ingreso)
            self._refrescar_lotes()
            QMessageBox.information(self.view, "Modificar lote", "Los datos del lote se guardaron correctamente.")
            self.log(f"[OK] Datos comerciales actualizados para lote {lote_texto}.")
        except Exception as e:
            QMessageBox.warning(self.view, "Modificar lote", f"No se pudieron guardar los cambios.\n\n{e}")

    def mostrar_pesajes(self):
        """Lista todos los ingresos y abre el seleccionado en modo seguro."""
        self._limpiar_ingreso_vacio()
        try:
            ingresos = PesajeService.todos_los_ingresos()
        except Exception as e:
            QMessageBox.warning(self.view, "Pesajes", f"No se pudieron cargar los ingresos.\n\n{e}")
            return
        if not ingresos:
            QMessageBox.information(self.view, "Pesajes", "Todavía no hay ingresos registrados.")
            return
        dialogo = PesajesView(ingresos, self.view)
        if dialogo.exec() != PesajesView.DialogCode.Accepted or not dialogo.id_seleccionado:
            return
        ingreso = PesajeModel.by_id(dialogo.id_seleccionado)
        if not ingreso:
            QMessageBox.warning(self.view, "Pesajes", "El ingreso seleccionado ya no existe.")
            return
        self.ingreso_actual = {"id_pesaje": ingreso["id_pesaje"], "ticket": ingreso["ticket"]}
        self.ultimo_peso = None
        self.view.preparar_nuevo_registro(ingreso["ticket"], ConfiguracionLotesModel.proximo_lote())
        self.view.cargar_datos_generales(ingreso)
        self.view.mostrar_ticket(ingreso["ticket"])
        self._refrescar_lotes()
        self.view.aplicar_modo_ingreso(ingreso["estado"])
        self.log(f"[CONSULTA] Ticket {ingreso['ticket']} abierto en estado {ingreso['estado']}.")

    def mostrar_pendientes(self):
        """
        Permite recuperar un ingreso EN_PROCESO.
        """

        # Si el ticket actual está vacío, se elimina.
        # Si ya tiene datos, permanece en SQLite.
        self._limpiar_ingreso_vacio()

        try:

            pendientes = PesajeService.ingresos_pendientes()

        except Exception as e:

            QMessageBox.warning(
                self.view,
                "Pesajes pendientes",
                f"No se pudieron cargar los pendientes.\n\n{e}",
            )

            return

        if not pendientes:

            QMessageBox.information(
                self.view,
                "Pesajes pendientes",
                "No hay ingresos pendientes.",
            )

            return

        dialogo = PendientesView(
            pendientes,
            self.view,
        )

        if dialogo.exec() != PendientesView.DialogCode.Accepted:
            return

        ingreso = PesajeModel.by_id(dialogo.id_seleccionado)

        if not ingreso:

            QMessageBox.warning(
                self.view,
                "Pesajes pendientes",
                "El ingreso seleccionado ya no existe.",
            )

            return

        self.ingreso_actual = {
            "id_pesaje": ingreso["id_pesaje"],
            "ticket": ingreso["ticket"],
        }

        # No debemos conservar un peso temporal de otro ingreso.
        self.ultimo_peso = None

        self.view.preparar_nuevo_registro(
            ingreso["ticket"],
            ConfiguracionLotesModel.proximo_lote(),
        )

        self.view.cargar_datos_generales(ingreso)

        self.view.mostrar_ticket(ingreso["ticket"])

        self._refrescar_lotes()

        self.log(f"[CONTINUAR] Ticket " f"{ingreso['ticket']} recuperado.")

    # ==================================================================
    # REFRESCAR TABLA
    # ==================================================================

    def _refrescar_lotes(self):

        if not self.ingreso_actual:
            return

        detalle = PesajeService.lotes_detalle(
            self.ingreso_actual["id_pesaje"], descendente=True
        )

        self._mapa_lotes = {d["lote"]: d["id_pesaje_lote"] for d in detalle}

        filas = PesajeService.filas_para_tabla(
            self.ingreso_actual["id_pesaje"], descendente=True
        )

        self.view.cargar_pesajes(filas)

    # ==================================================================
    # SERIAL - DETECTAR PUERTOS
    # ==================================================================

    def detectar_puertos(self):
        """
        Detecta los puertos COM disponibles y los coloca
        en los combos de balanza y display.
        """

        # Mientras esperamos comunicación no se deben modificar
        # los puertos seleccionados.
        if self.esperando_balanza:
            return

        # Mientras está funcionando tampoco.
        if self.balanza_comunicando:
            return

        self.view.configuracion.cmb_balanza.clear()
        self.view.configuracion.cmb_display.clear()

        try:

            puertos = serial.tools.list_ports.comports()

            for puerto in puertos:

                descripcion = puerto.description or "Sin descripción"

                texto = f"{puerto.device} - " f"{descripcion}"

                self.view.configuracion.cmb_balanza.addItem(
                    texto,
                    puerto.device,
                )

                self.view.configuracion.cmb_display.addItem(
                    texto,
                    puerto.device,
                )

            # Seleccionar puertos configurados por defecto.
            self.seleccionar_puerto(
                self.view.configuracion.cmb_balanza,
                PUERTO_BALANZA_DEFAULT,
            )

            self.seleccionar_puerto(
                self.view.configuracion.cmb_display,
                PUERTO_DISPLAY_DEFAULT,
            )

            self.log("[INFO] Puertos actualizados.")

        except Exception as e:

            self.log(f"[ERROR PUERTOS] {e}")

    def seleccionar_puerto(
        self,
        combo,
        puerto_objetivo,
    ):
        """
        Selecciona en un QComboBox el puerto cuyo itemData
        coincide con puerto_objetivo.
        """

        for indice in range(combo.count()):

            if combo.itemData(indice) == puerto_objetivo:

                combo.setCurrentIndex(indice)
                return True

        return False

    # ==================================================================
    # SERIAL - INICIAR
    # ==================================================================

    def iniciar(self):
        """
        Abre la balanza y el display y comienza la lectura.
        """

        puerto_balanza = self.view.configuracion.cmb_balanza.currentData()

        puerto_display = self.view.configuracion.cmb_display.currentData()

        # --------------------------------------------------------------
        # Validar puertos
        # --------------------------------------------------------------

        if not puerto_balanza:

            QMessageBox.warning(
                self.view,
                "Configuración",
                "Seleccione el puerto de la balanza.",
            )

            return

        if not puerto_display:

            QMessageBox.warning(
                self.view,
                "Configuración",
                "Seleccione el puerto del display.",
            )

            return

        if puerto_balanza == puerto_display:

            QMessageBox.warning(
                self.view,
                "Configuración",
                ("La balanza y el display deben utilizar " "puertos diferentes."),
            )

            return

        try:

            # ----------------------------------------------------------
            # Crear servicio de balanza
            # ----------------------------------------------------------

            self.balanza = SerialBalanza(
                puerto=puerto_balanza,
                baudrate=(self.view.configuracion.spin_baudrate_balanza.value()),
                timeout=SERIAL_TIMEOUT,
            )

            self.balanza.conectar()

            # ----------------------------------------------------------
            # Crear servicio de display
            # ----------------------------------------------------------

            self.display = SerialDisplay(
                puerto=puerto_display,
                baudrate=(self.view.configuracion.spin_baudrate_display.value()),
                timeout=SERIAL_TIMEOUT,
            )

            self.display.conectar()

            # ----------------------------------------------------------
            # Estado interno
            # ----------------------------------------------------------

            self.esperando_balanza = True
            self.balanza_comunicando = False
            self.ultimo_peso = None

            # ----------------------------------------------------------
            # Estado visual - balanza
            # ----------------------------------------------------------

            self.view.estado_balanza(
                (f"🟡 Balanza: {puerto_balanza} " "- esperando señal..."),
                "#b88600",
            )

            # ----------------------------------------------------------
            # Estado visual - display
            # ----------------------------------------------------------

            self.view.estado_display(
                (f"🟢 Puerto display abierto: " f"{puerto_display}"),
                "green",
            )

            # ----------------------------------------------------------
            # Estado visual - sistema
            # ----------------------------------------------------------

            self.view.estado_sistema(
                "🟡 Esperando comunicación de la balanza...",
                "#b88600",
            )

            self.view.lbl_peso.setText("---")

            # ----------------------------------------------------------
            # Bloquear configuración
            # ----------------------------------------------------------

            self.view.btn_iniciar.setEnabled(False)
            self.view.btn_detener.setEnabled(True)

            self.view.bloquear_configuracion(True)

            # ----------------------------------------------------------
            # Log
            # ----------------------------------------------------------

            self.log("")
            self.log("[INICIO] Sistema iniciando...")
            self.log(f"[INFO] Balanza: {puerto_balanza}")
            self.log(f"[INFO] Display: {puerto_display}")
            self.log("[INFO] Esperando datos de la balanza...")

            # ----------------------------------------------------------
            # Iniciar timers
            # ----------------------------------------------------------

            self.timer.start()
            self.timer_inicio.start()

        except serial.SerialException as e:

            self.timer.stop()
            self.timer_inicio.stop()

            self.cerrar()
            self.restaurar_controles()

            self.esperando_balanza = False
            self.balanza_comunicando = False

            self.view.estado_balanza(
                "🔴 Error al abrir la balanza",
                "red",
            )

            self.view.estado_display(
                "🔴 Error al abrir el display",
                "red",
            )

            self.view.estado_sistema(
                "🔴 Error al abrir los puertos",
                "red",
            )

            QMessageBox.critical(
                self.view,
                "Error de conexión",
                ("No se pudieron abrir los puertos.\n\n" f"{e}"),
            )

        except Exception as e:

            self.timer.stop()
            self.timer_inicio.stop()

            self.cerrar()
            self.restaurar_controles()

            self.esperando_balanza = False
            self.balanza_comunicando = False

            self.view.estado_sistema(
                "🔴 Error al iniciar",
                "red",
            )

            QMessageBox.critical(
                self.view,
                "Error",
                str(e),
            )

    # ==================================================================
    # SERIAL - PROCESAR BALANZA
    # ==================================================================

    def procesar_balanza(self):
        """
        Lee las tramas recibidas por la balanza, extrae el peso
        y lo muestra en pantalla.

        IMPORTANTE:
        El peso NO se guarda en SQLite aquí.
        Solo se conserva como último peso válido.

        El guardado real ocurre cuando el usuario presiona
        "Capturar peso".
        """

        if not self.balanza:
            return

        try:

            cadena = self.balanza.leer()

            if not cadena:
                return

            self.log(f"BALANZA → {repr(cadena)}")

            # ----------------------------------------------------------
            # Separar tramas
            # ----------------------------------------------------------

            lineas = cadena.replace("\r", "\n").split("\n")

            for linea in lineas:

                linea = linea.strip()

                if not linea:
                    continue

                # ------------------------------------------------------
                # Parser
                # ------------------------------------------------------

                peso = ParserPeso.extraer(linea)

                if peso is None:
                    continue

                # ------------------------------------------------------
                # Primera comunicación válida
                # ------------------------------------------------------

                if not self.balanza_comunicando:

                    self.balanza_comunicando = True
                    self.esperando_balanza = False

                    self.timer_inicio.stop()

                    self.view.estado_balanza(
                        "🟢 Balanza comunicando",
                        "green",
                    )

                    self.view.estado_display(
                        "🟢 Display listo",
                        "green",
                    )

                    self.view.estado_sistema(
                        "🟢 Sistema funcionando",
                        "green",
                    )

                    self.log("[OK] Señal de balanza detectada.")

                    self.log("[OK] Sistema funcionando.")

                # ------------------------------------------------------
                # Guardar último peso válido
                # ------------------------------------------------------

                self.ultimo_peso = peso

                # ------------------------------------------------------
                # Mostrar peso
                # ------------------------------------------------------

                self.view.mostrar_peso(peso)

                # ------------------------------------------------------
                # Enviar al display
                # ------------------------------------------------------

                self.enviar_display(peso)

        except serial.SerialException as e:

            self.log(f"[ERROR BALANZA] {e}")

            self.detener()

            QMessageBox.critical(
                self.view,
                "Error de balanza",
                ("Se perdió la comunicación con la balanza.\n\n" f"{e}"),
            )

        except Exception as e:

            self.log(f"[ERROR BALANZA] {e}")

    # ==================================================================
    # SERIAL - DISPLAY
    # ==================================================================

    def enviar_display(self, peso):
        """
        Envía el peso actual al display.
        """

        if not self.display:
            return

        try:

            mensaje = self.display.enviar_peso(peso)

            if mensaje:

                self.log(f"DISPLAY ← {repr(mensaje)}")

        except serial.SerialException as e:

            self.log(f"[ERROR DISPLAY] {e}")

        except Exception as e:

            self.log(f"[ERROR DISPLAY] {e}")

    # ==================================================================
    # SERIAL - TIMEOUT DE INICIO
    # ==================================================================

    def error_inicio(self):
        """
        Se ejecuta si transcurre el tiempo configurado y la balanza
        nunca envió una trama válida.
        """

        # Si ya empezó a comunicar, no hacer nada.
        if self.balanza_comunicando:
            return

        self.esperando_balanza = False

        self.timer.stop()

        self.log("[ERROR] Tiempo de espera agotado.")

        self.cerrar()

        self.view.estado_balanza(
            "🔴 Sin comunicación con la balanza",
            "red",
        )

        self.view.estado_display(
            "⚪ Display detenido",
            "#555",
        )

        self.view.estado_sistema(
            "🔴 No se detectó señal de balanza",
            "red",
        )

        self.restaurar_controles()

        QMessageBox.warning(
            self.view,
            "Sin comunicación",
            (
                "No se recibió una señal válida de la balanza "
                "dentro del tiempo de espera.\n\n"
                "Verifique:\n"
                "• Que la balanza esté encendida.\n"
                "• Que el cable esté conectado.\n"
                "• Que el puerto COM sea correcto.\n"
                "• Que la velocidad sea correcta.\n"
                "• Que la configuración sea 9600, 8N1."
            ),
        )

    # ==================================================================
    # SERIAL - DETENER
    # ==================================================================

    def detener(self):
        """
        Detiene la lectura y cierra los puertos seriales.
        """

        self.timer.stop()
        self.timer_inicio.stop()

        self.esperando_balanza = False
        self.balanza_comunicando = False
        self.ultimo_peso = None

        self.cerrar()

        self.view.lbl_peso.setText("---")

        self.view.estado_balanza(
            "🔴 Balanza desconectada",
            "red",
        )

        self.view.estado_display(
            "🔴 Display desconectado",
            "red",
        )

        self.view.estado_sistema(
            "Detenido",
            "#555",
        )

        self.restaurar_controles()

        self.log("[SISTEMA DETENIDO]")

    # ==================================================================
    # SERIAL - CERRAR PUERTOS
    # ==================================================================

    def cerrar(self):
        """
        Cierra las conexiones seriales.
        """

        try:

            if self.balanza:

                self.balanza.cerrar()

        except Exception as e:

            self.log(f"[ERROR CERRANDO BALANZA] {e}")

        finally:

            self.balanza = None

        try:

            if self.display:

                self.display.cerrar()

        except Exception as e:

            self.log(f"[ERROR CERRANDO DISPLAY] {e}")

        finally:

            self.display = None

    # ==================================================================
    # RESTAURAR CONTROLES
    # ==================================================================

    def restaurar_controles(self):
        """
        Deja nuevamente disponibles los controles seriales.
        """

        self.view.btn_iniciar.setEnabled(True)
        self.view.btn_detener.setEnabled(False)

        self.view.bloquear_configuracion(False)

    # LOG
    def imprimir_lote(self):
        """Genera el ticket PDF únicamente del lote seleccionado en la tabla."""
        lote_texto = self.view.obtener_fila_lote_seleccionada()

        if not lote_texto:
            QMessageBox.information(
                self.view,
                "Imprimir ticket",
                "Seleccione un lote de la tabla antes de imprimir.",
            )
            return

        id_lote = self._mapa_lotes.get(lote_texto)
        if id_lote is None:
            QMessageBox.warning(
                self.view,
                "Imprimir ticket",
                "No se pudo identificar el lote seleccionado. Actualice la tabla e inténtelo nuevamente.",
            )
            return

        try:
            parametros = PesajeService.preparar_datos_ticket(id_lote)
            ruta_pdf = ReportePdfService.generar_ticket(parametros)
            self.log(
                f"[PDF] Ticket del lote {lote_texto} generado: {ruta_pdf}"
            )
        except ReglaNegocioError as e:
            QMessageBox.warning(self.view, "Imprimir ticket", str(e))
        except Exception as e:
            self.log(f"[ERROR PDF] No se pudo imprimir el lote {lote_texto}: {e}")
            QMessageBox.critical(
                self.view,
                "Error al generar el ticket",
                f"No se pudo generar el PDF del lote seleccionado.\n\n{e}",
            )

    def log(self, texto):
        self.view.log(texto)
