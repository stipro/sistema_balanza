from PyQt6.QtCore import QTimer, QSettings
from PyQt6.QtWidgets import QMessageBox

import serial
import serial.tools.list_ports

from services.serial_balanza import SerialBalanza
from services.serial_display import SerialDisplay
from utils.parser_peso import ParserPeso

from models.base import ReglaNegocioError
from services.api_conductores_service import ApiConductoresService
from services.api_proveedores_service import ApiProveedoresService
from services.api_transportistas_service import ApiTransportistasService
from services.api_concesiones_service import ApiConcesionesService
from services.api_vehiculos_service import ApiVehiculosService
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
        self.view.btn_eliminar_lote.clicked.connect(self.eliminar_lote_seleccionado)
        self.view.btn_eliminar_ticket.clicked.connect(self.eliminar_ticket_actual)
        self.view.btn_pendientes.clicked.connect(self.mostrar_pesajes)
        # Al seleccionar un lote, cargar sus datos comerciales en el formulario.
        self.view.tabla_pesajes.itemSelectionChanged.connect(
            self.cargar_lote_seleccionado
        )
        self.view.tabla_pesajes.itemChanged.connect(self._peso_tabla_editado)
        self._procesando_edicion_peso = False

        # Configuración de lotes
        self.view.configuracion_lotes.btn_guardar.clicked.connect(
            self.guardar_configuracion_lotes
        )

        # CONFIGURACIÓN SERIAL PERSISTENTE

        self.config_serial = QSettings("MineraMH", "SistemaBalanza")

        # Recuperar velocidades guardadas.
        self.view.configuracion.spin_baudrate_balanza.setValue(
            self.config_serial.value(
                "serial/baudrate_balanza",
                BAUDRATE_BALANZA_DEFAULT,
                type=int,
            )
        )

        self.view.configuracion.spin_baudrate_display.setValue(
            self.config_serial.value(
                "serial/baudrate_display",
                BAUDRATE_DISPLAY_DEFAULT,
                type=int,
            )
        )

        # Guardar automáticamente cuando cambie una selección.
        self.view.configuracion.cmb_balanza.currentIndexChanged.connect(
            self.guardar_configuracion_serial
        )

        self.view.configuracion.cmb_display.currentIndexChanged.connect(
            self.guardar_configuracion_serial
        )

        self.view.configuracion.spin_baudrate_balanza.valueChanged.connect(
            self.guardar_configuracion_serial
        )

        self.view.configuracion.spin_baudrate_display.valueChanged.connect(
            self.guardar_configuracion_serial
        )

        self.view.configuracion.btn_actualizar.clicked.connect(
            self.detectar_puertos
        )

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
        Sincroniza conductores, proveedores, transportistas y concesiones
        desde la API comercial. Después recarga los maestros desde SQLite.

        Los modelos conservan sus IDs locales para no afectar pesajes históricos.
        """
        try:
            self.view.btn_actualizar_maestros.setEnabled(False)
            self.view.btn_actualizar_maestros.setText("Sincronizando...")

            # 1. Consultar una sola vez el catálogo comercial y separar por tipo.
            registros_vehiculos = ApiVehiculosService.obtener_vehiculos()
            resultado_vehiculos = VehiculoModel.sincronizar_desde_api(
                registros_vehiculos
            )
            resultado_carretas = CarretaModel.sincronizar_desde_api(
                registros_vehiculos
            )

            # 2. Sincronizar conductores.
            registros_conductores = ApiConductoresService.obtener_conductores()
            resultado_conductores = ConductorModel.sincronizar_desde_api(
                registros_conductores
            )

            # 3. Sincronizar proveedores.
            registros_proveedores = ApiProveedoresService.obtener_proveedores()
            resultado_proveedores = ProveedorModel.sincronizar_desde_api(
                registros_proveedores
            )

            # 4. Sincronizar transportistas.
            registros_transportistas = ApiTransportistasService.obtener_transportistas()
            resultado_transportistas = TransportistaModel.sincronizar_desde_api(
                registros_transportistas
            )

            # 5. Sincronizar concesiones.
            registros_concesiones = ApiConcesionesService.obtener_concesiones()
            resultado_concesiones = ConcesionModel.sincronizar_desde_api(
                registros_concesiones
            )

            # 6. Recargar todos los maestros desde SQLite.
            self.cargar_maestros()

            self.log(
                "[OK] Vehículos: "
                f"{resultado_vehiculos['insertados']} nuevos, "
                f"{resultado_vehiculos['actualizados']} actualizados."
            )
            self.log(
                "[OK] Carretas: "
                f"{resultado_carretas['insertados']} nuevas, "
                f"{resultado_carretas['actualizados']} actualizadas."
            )
            self.log(
                "[OK] Conductores: "
                f"{resultado_conductores['insertados']} nuevos, "
                f"{resultado_conductores['actualizados']} actualizados, "
                f"{resultado_conductores['desactivados']} desactivados."
            )
            self.log(
                "[OK] Proveedores: "
                f"{resultado_proveedores['insertados']} nuevos, "
                f"{resultado_proveedores['actualizados']} actualizados."
            )
            self.log(
                "[OK] Transportistas: "
                f"{resultado_transportistas['insertados']} nuevos, "
                f"{resultado_transportistas['actualizados']} actualizados."
            )
            self.log(
                "[OK] Concesiones: "
                f"{resultado_concesiones['insertados']} nuevas, "
                f"{resultado_concesiones['actualizados']} actualizadas."
            )

            QMessageBox.information(
                self.view,
                "Actualizar maestros",
                "Sincronización completada.\n\n"
                "CARRETAS (solo tipo CARRETA)\n"
                f"Nuevas: {resultado_carretas['insertados']}\n"
                f"Actualizadas: {resultado_carretas['actualizados']}\n\n"
                "VEHÍCULOS (CAMION y TRACTO)\n"
                f"Nuevos: {resultado_vehiculos['insertados']}\n"
                f"Actualizados: {resultado_vehiculos['actualizados']}\n\n"
                "CONDUCTORES\n"
                f"Nuevos: {resultado_conductores['insertados']}\n"
                f"Actualizados: {resultado_conductores['actualizados']}\n"
                f"Desactivados: {resultado_conductores['desactivados']}\n\n"
                "PROVEEDORES\n"
                f"Nuevos: {resultado_proveedores['insertados']}\n"
                f"Actualizados: {resultado_proveedores['actualizados']}\n\n"
                "TRANSPORTISTAS\n"
                f"Nuevos: {resultado_transportistas['insertados']}\n"
                f"Actualizados: {resultado_transportistas['actualizados']}\n\n"
                "CONCESIONES\n"
                f"Nuevas: {resultado_concesiones['insertados']}\n"
                f"Actualizadas: {resultado_concesiones['actualizados']}\n\n"
                "Los demás maestros se recargaron desde SQLite."
            )

        except Exception as e:
            self.log(f"[ERROR MAESTROS] {e}")
            QMessageBox.warning(
                self.view,
                "Actualizar maestros",
                "No se pudo completar la sincronización de maestros.\n\n"
                f"{e}\n\n"
                "Los datos locales existentes se conservaron."
            )
            try:
                self.cargar_maestros()
            except Exception as error_carga:
                self.log(f"[ERROR CARGA MAESTROS] {error_carga}")
        finally:
            self.view.btn_actualizar_maestros.setEnabled(True)
            self.view.btn_actualizar_maestros.setText("🔄  Actualizar maestros")

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
        """Cierra el contexto visual; nunca elimina un ticket automáticamente.

        La eliminación de tickets es explícita mediante ELIMINAR TICKET.
        """
        if self.ingreso_actual:
            self.log(
                f"[INFO] Se cerró la vista del ticket "
                f"{self.ingreso_actual['ticket']}; no se eliminó automáticamente."
            )
        self.ingreso_actual = None
        self.ultimo_peso = None

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

        celda = self._celda_peso_seleccionada()
        if celda:
            self._corregir_pesaje_seleccionado(celda)
            return

        try:
            # Sincronizar datos generales del ingreso
            self._sincronizar_datos_generales()

            # Los datos del formulario solo se usan si la operación aún no
            # tiene ningún lote ni captura (creación del primer lote).
            # La existencia de una selección en la tabla nunca debe provocar
            # la creación automática de otro lote.
            datos_lote = self.view.obtener_datos_lote()
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

    def _celda_peso_seleccionada(self):
        """Devuelve el peso capturado de la celda actual, si corresponde."""
        tabla = self.view.tabla_pesajes
        if not tabla.selectionModel().hasSelection():
            return None
        fila = tabla.currentRow()
        columna = tabla.currentColumn()
        if fila < 0 or columna not in (3, 5):
            return None
        item_lote = tabla.item(fila, 0)
        item_peso = tabla.item(fila, columna)
        if item_lote is None or item_peso is None or not item_peso.text().strip():
            return None
        id_lote = self._mapa_lotes.get(item_lote.text().strip())
        if id_lote is None:
            return None
        lote = PesajeLoteModel.by_id(id_lote)
        if not lote:
            return None
        tipo = "BRUTO" if columna == 3 else "TARA"
        id_registro = lote.get(
            "id_registro_bruto" if tipo == "BRUTO" else "id_registro_tara"
        )
        if id_registro is None:
            return None
        return {
            "id_lote": id_lote,
            "lote": item_lote.text().strip(),
            "tipo": tipo,
        }

    def _actualizar_boton_captura_segun_celda(self):
        celda = self._celda_peso_seleccionada()
        if celda:
            self.view.btn_capturar.setText(f"⚖  CORREGIR {celda['tipo']}")
        else:
            self.view.btn_capturar.setText("⚖  CAPTURAR PESO")

        if self.ingreso_actual:
            ingreso = PesajeModel.by_id(self.ingreso_actual["id_pesaje"])
            if ingreso and ingreso.get("estado") != "EN_PROCESO":
                self.view.btn_capturar.setEnabled(
                    bool(celda)
                    and ingreso.get("estado") == "CONFIRMADO"
                    and not ingreso.get("sincronizado")
                    and self.balanza_comunicando
                )

    def _corregir_pesaje_seleccionado(self, celda):
        id_pesaje = self.ingreso_actual["id_pesaje"]
        try:
            previo = PesajeService.previsualizar_correccion_pesaje(
                id_pesaje, celda["id_lote"], celda["tipo"], self.ultimo_peso
            )
        except ReglaNegocioError as e:
            QMessageBox.warning(self.view, "Corregir pesada", str(e))
            return
        except Exception as e:
            QMessageBox.critical(
                self.view, "Error al corregir pesada",
                f"No se pudo corregir la captura. No se aplicaron cambios.\n\n{e}",
            )
            return

        detalle_afectados = []
        for afectado in previo["afectados"]:
            linea = f"• Lote {afectado['lote']}"
            if afectado["neto_anterior"] is not None:
                linea += (
                    f": neto {afectado['neto_anterior']} kg → "
                    f"{afectado['neto_nuevo']} kg"
                )
            detalle_afectados.append(linea)
        mensaje = (
            f"Se reemplazará la captura {previo['secuencia']} seleccionada "
            f"como {previo['tipo']} del lote {previo['lote_seleccionado']}.\n\n"
            f"Peso actual: {previo['peso_anterior']} kg\n"
            f"Nuevo peso: {previo['peso_nuevo']} kg\n\n"
            "Lotes afectados:\n" + "\n".join(detalle_afectados)
            + "\n\n¿Desea continuar?"
        )
        respuesta = QMessageBox.question(
            self.view, "Confirmar corrección de pesada", mensaje,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if respuesta != QMessageBox.StandardButton.Yes:
            return

        motivo, ok = self.view.pedir_motivo("Corregir pesada")
        if not ok or not motivo:
            return

        try:
            resultado = PesajeService.corregir_pesaje(
                id_pesaje, celda["id_lote"], celda["tipo"], self.ultimo_peso, motivo
            )
            self.log(
                f"[CORRECCIÓN PESO] Captura #{resultado['secuencia']} "
                f"{resultado['peso_anterior']} -> {resultado['peso_nuevo']} kg. "
                f"Motivo: {motivo}"
            )
            self.view.tabla_pesajes.clearSelection()
            self.view.tabla_pesajes.setCurrentItem(None)
            self._actualizar_boton_captura_segun_celda()
            self._refrescar_lotes()
            QMessageBox.information(
                self.view, "Corregir pesada",
                "La pesada fue corregida y se recalcularon los pesos netos afectados.",
            )
        except ReglaNegocioError as e:
            QMessageBox.warning(self.view, "Corregir pesada", str(e))
        except Exception as e:
            QMessageBox.critical(
                self.view, "Error al corregir pesada",
                f"No se pudo corregir la captura. No se aplicaron cambios.\n\n{e}",
            )

    def _peso_tabla_editado(self, item):
        """Registra en el historial una edición manual de bruto o tara."""
        if self._procesando_edicion_peso or item.column() not in (2, 3, 4, 5):
            return
        if not self.ingreso_actual:
            self._refrescar_lotes()
            return

        celda_lote = self.view.tabla_pesajes.item(item.row(), 0)
        id_lote = self._mapa_lotes.get(celda_lote.text().strip()) if celda_lote else None
        if id_lote is None:
            self._refrescar_lotes()
            return

        tipo = "BRUTO" if item.column() in (2, 3) else "TARA"
        es_fecha = item.column() in (2, 4)
        id_pesaje = self.ingreso_actual["id_pesaje"]
        valor_nuevo = item.text().strip()
        try:
            if es_fecha:
                previo = PesajeService.previsualizar_correccion_fecha(
                    id_pesaje, id_lote, tipo, valor_nuevo
                )
            else:
                previo = PesajeService.previsualizar_correccion_pesaje(
                    id_pesaje, id_lote, tipo, valor_nuevo
                )
        except ReglaNegocioError as e:
            self._procesando_edicion_peso = True
            try:
                QMessageBox.warning(self.view, "Corregir pesada", str(e))
            finally:
                self._procesando_edicion_peso = False
                self._refrescar_lotes()
            return
        except Exception as e:
            self._procesando_edicion_peso = True
            try:
                QMessageBox.critical(
                    self.view, "Error al corregir pesada",
                    f"No se pudo corregir la captura. No se aplicaron cambios.\n\n{e}",
                )
            finally:
                self._procesando_edicion_peso = False
                self._refrescar_lotes()
            return

        afectados = []
        for lote_afectado in previo["afectados"]:
            linea = f"• Lote {lote_afectado['lote']}"
            if es_fecha:
                linea += f": {PesajeService.formatear_fecha_hora(lote_afectado['fecha_nueva'])}"
            elif lote_afectado["neto_anterior"] is not None:
                linea += (
                    f": neto {lote_afectado['neto_anterior']} kg → "
                    f"{lote_afectado['neto_nuevo']} kg"
                )
            afectados.append(linea)
        if es_fecha:
            detalle_valor = (
                f"Fecha/hora actual: {PesajeService.formatear_fecha_hora(previo['fecha_hora_anterior'])}\n"
                f"Fecha/hora nueva: {PesajeService.formatear_fecha_hora(previo['fecha_hora_nueva'])}"
            )
        else:
            detalle_valor = (
                f"Peso actual: {previo['peso_anterior']} kg\n"
                f"Nuevo peso: {previo['peso_nuevo']} kg"
            )
        mensaje = (
            detalle_valor + "\n\nLotes afectados:\n" + "\n".join(afectados)
            + "\n\n¿Desea guardar esta corrección?"
        )
        respuesta = QMessageBox.question(
            self.view, "Confirmar corrección de pesada", mensaje,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if respuesta != QMessageBox.StandardButton.Yes:
            self._refrescar_lotes()
            return

        motivo, ok = self.view.pedir_motivo("Corregir pesada")
        if not ok or not motivo:
            self._refrescar_lotes()
            return

        try:
            if es_fecha:
                resultado = PesajeService.corregir_fecha_pesaje(
                    id_pesaje, id_lote, tipo, valor_nuevo, motivo
                )
                detalle = (
                    f"{resultado['fecha_hora_anterior']} -> "
                    f"{resultado['fecha_hora_nueva']}"
                )
            else:
                resultado = PesajeService.corregir_pesaje(
                    id_pesaje, id_lote, tipo, valor_nuevo, motivo
                )
                detalle = (
                    f"{resultado['peso_anterior']} -> {resultado['peso_nuevo']} kg"
                )
            self.log(
                f"[CORRECCIÓN MANUAL] Captura #{resultado['secuencia']} "
                f"{detalle}. Motivo: {motivo}"
            )
            QMessageBox.information(
                self.view, "Corregir pesada",
                (
                    "La fecha y hora fueron actualizadas en los lotes relacionados."
                    if es_fecha else
                    "La pesada fue corregida y se recalcularon los pesos netos afectados."
                ),
            )
        except ReglaNegocioError as e:
            QMessageBox.warning(self.view, "Corregir pesada", str(e))
        except Exception as e:
            QMessageBox.critical(
                self.view, "Error al corregir pesada",
                f"No se pudo corregir la captura. No se aplicaron cambios.\n\n{e}",
            )
        finally:
            self._refrescar_lotes()

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

    def eliminar_lote_seleccionado(self):
        """Elimina solo el lote seleccionado si la cadena lo permite."""
        if not self.ingreso_actual:
            QMessageBox.information(self.view, "Eliminar lote", "Primero abra un ticket.")
            return
        lote_texto = self.view.obtener_fila_lote_seleccionada()
        if not lote_texto or lote_texto not in self._mapa_lotes:
            QMessageBox.information(self.view, "Eliminar lote", "Seleccione un lote en la tabla.")
            return
        id_lote = self._mapa_lotes[lote_texto]
        respuesta = QMessageBox.question(
            self.view,
            "Confirmar eliminación",
            f"¿Eliminar el lote {lote_texto} del ticket {self.ingreso_actual['ticket']}?\n\n"
            "Se guardará una copia en el historial. Esta acción no se puede deshacer desde la pantalla operativa.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if respuesta != QMessageBox.StandardButton.Yes:
            return
        try:
            resultado = PesajeService.eliminar_lote(id_lote)
            self._lote_en_edicion = None
            self.view.btn_modificar.setText("✎  MODIFICAR")
            # Actualizar la tabla después de eliminar el lote.
            self._refrescar_lotes()
            # Limpiar los campos correspondientes al lote eliminado.
            self.view.limpiar_campos_lote()
            # Mostrar el correlativo disponible.
            self.view.mostrar_proximo_lote(ConfiguracionLotesModel.proximo_lote())
            # El ticket sigue activo: volver a habilitar el formulario.
            self.view.aplicar_modo_ingreso("EN_PROCESO")
            mensaje = f"El lote {resultado['lote']} fue eliminado y archivado en el historial."
            if resultado.get("correlativo_recuperado"):
                mensaje += "\nSe recuperó el último correlativo disponible."
            QMessageBox.information(self.view, "Lote eliminado", mensaje)
            self.log(f"[ELIMINAR LOTE] {resultado['lote']} del ticket {resultado['ticket']} archivado en historial.")
        except ReglaNegocioError as e:
            QMessageBox.warning(self.view, "No se puede eliminar el lote", str(e))
        except Exception as e:
            QMessageBox.critical(self.view, "Error al eliminar lote", f"No se pudo eliminar el lote.\n\n{e}")

    def eliminar_ticket_actual(self):
        """Elimina explícitamente el ticket actual, únicamente si está vacío."""
        if not self.ingreso_actual:
            QMessageBox.information(self.view, "Eliminar ticket", "No hay un ticket activo.")
            return
        ticket = self.ingreso_actual["ticket"]
        respuesta = QMessageBox.question(
            self.view,
            "Confirmar eliminación de ticket",
            f"¿Eliminar el ticket vacío {ticket}?\n\nSolo se permite si no tiene lotes ni capturas.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if respuesta != QMessageBox.StandardButton.Yes:
            return
        try:
            ticket_eliminado = PesajeService.eliminar_ticket_vacio(self.ingreso_actual["id_pesaje"])
            self.ingreso_actual = None
            self.ultimo_peso = None
            self._mapa_lotes = {}
            self._lote_en_edicion = None
            self.view.cargar_pesajes([])
            self.view.estado_operacion("sin_operacion")
            self.view.bloquear_formulario(True)
            self.view.mostrar_ticket("")
            QMessageBox.information(self.view, "Ticket eliminado", f"El ticket {ticket_eliminado} fue eliminado y registrado en el historial.")
            self.log(f"[ELIMINAR TICKET] Ticket {ticket_eliminado} vacío eliminado.")
        except ReglaNegocioError as e:
            QMessageBox.warning(self.view, "No se puede eliminar el ticket", str(e))
        except Exception as e:
            QMessageBox.critical(self.view, "Error al eliminar ticket", f"No se pudo eliminar el ticket.\n\n{e}")

    def cargar_lote_seleccionado(self):
        """Muestra en el formulario los datos del lote seleccionado.

        La selección solo consulta/carga datos; guardar cambios sigue siendo
        responsabilidad del botón MODIFICAR y de PesajeService.
        """

        """Carga el lote seleccionado o limpia su selección visual."""
        lote_texto = self.view.obtener_fila_lote_seleccionada()

        if not lote_texto:
            self._lote_en_edicion = None
            self.view.btn_modificar.setText("✎  MODIFICAR")
            self._actualizar_boton_captura_segun_celda()

            if self.ingreso_actual:
                self.view.limpiar_campos_lote()
                ingreso = PesajeModel.by_id(self.ingreso_actual["id_pesaje"])
                estado = ingreso.get("estado") if ingreso else "EN_PROCESO"
                if estado == "EN_PROCESO":
                    self.view.mostrar_proximo_lote(
                        ConfiguracionLotesModel.proximo_lote()
                    )
                self.view.aplicar_modo_ingreso(estado)

            return
    
        if not self.ingreso_actual:
            return

        lote_texto = self.view.obtener_fila_lote_seleccionada()
        if not lote_texto:
            return

        id_lote = self._mapa_lotes.get(lote_texto)
        if not id_lote:
            return

        try:
            if self._lote_en_edicion == id_lote:
                # Cambiar de celda dentro de la misma fila no debe cancelar
                # ni volver a bloquear una edición ya abierta.
                self._actualizar_boton_captura_segun_celda()
                return

            self._lote_en_edicion = None
            lote = PesajeLoteModel.detalle_por_id(id_lote)
            if not lote:
                return

            # No recargar el mismo lote repetidamente si el cambio de selección
            # fue provocado por un refresco de la tabla.
            self.view.cargar_datos_lote(lote)
            self._actualizar_boton_captura_segun_celda()

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
            self.view.bloquear_campos_comerciales(False)
            # El lote puede renombrarse mientras el ingreso sigue abierto.
            # En un ingreso confirmado se conserva como identificador fijo.
            self.view.txt_lote.setEnabled(estado_ingreso == "EN_PROCESO")
            # Placa y carreta pertenecen al ingreso (ticket), por eso se
            # modifican desde el lote seleccionado y se guardan en pesajes.
            self.view.habilitar_edicion_vehiculo(True)
            return

        # Segundo clic: persistir solo los campos comerciales permitidos.
        try:
            datos = self.view.obtener_datos_lote()
            if estado_ingreso != "EN_PROCESO":
                datos.pop("lote", None)
            # Persistir placa/carreta en el ingreso asociado al lote.
            self._sincronizar_datos_generales()
            PesajeService.actualizar_lote(id_lote, datos)
            self._lote_en_edicion = None
            self.view.btn_modificar.setText("✎  MODIFICAR")
            # La edición termina quitando la selección. La tabla no debe
            # conservar visualmente un lote cuyo formulario ya fue guardado.
            self.view.tabla_pesajes.clearSelection()
            self.view.tabla_pesajes.setCurrentItem(None)
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

    def limpiar_seleccion_lote(self):
        """Quita la selección y permite continuar agregando lotes."""
        self._lote_en_edicion = None

        # Restablecer el botón de modificación.
        self.view.btn_modificar.setText("✎  MODIFICAR")

        # Quitar la selección de la tabla.
        self.view.tabla_pesajes.clearSelection()
        self.view.tabla_pesajes.setCurrentItem(None)

        # Limpiar los campos propios del lote.
        self.view.limpiar_campos_lote()

        # Habilitar nuevamente el formulario para ingresar otro lote.
        self.view.aplicar_modo_ingreso("EN_PROCESO")

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

        procesando = self._procesando_edicion_peso
        self._procesando_edicion_peso = True
        try:
            self.view.cargar_pesajes(filas)
        finally:
            self._procesando_edicion_peso = procesando

    def guardar_configuracion_serial(self, *_args):
        """Guarda los puertos y las velocidades para próximas sesiones."""

        if not hasattr(self, "config_serial"):
            return

        config = self.view.configuracion

        puerto_balanza = config.cmb_balanza.currentData()
        puerto_display = config.cmb_display.currentData()

        if puerto_balanza:
            self.config_serial.setValue(
                "serial/puerto_balanza",
                puerto_balanza,
            )

        if puerto_display:
            self.config_serial.setValue(
                "serial/puerto_display",
                puerto_display,
            )

        self.config_serial.setValue(
            "serial/baudrate_balanza",
            config.spin_baudrate_balanza.value(),
        )

        self.config_serial.setValue(
            "serial/baudrate_display",
            config.spin_baudrate_display.value(),
        )

        self.config_serial.sync()

    # ==================================================================
    # SERIAL - DETECTAR PUERTOS
    # ==================================================================

    def detectar_puertos(self):
        """Detecta los puertos disponibles y restaura la selección guardada."""

        if self.esperando_balanza or self.balanza_comunicando:
            return

        cmb_balanza = self.view.configuracion.cmb_balanza
        cmb_display = self.view.configuracion.cmb_display

        # Evitar que las modificaciones temporales disparen el guardado.
        cmb_balanza.blockSignals(True)
        cmb_display.blockSignals(True)

        try:
            cmb_balanza.clear()
            cmb_display.clear()

            puertos = serial.tools.list_ports.comports()

            for puerto in puertos:
                descripcion = puerto.description or "Sin descripción"
                texto = f"{puerto.device} - {descripcion}"

                cmb_balanza.addItem(texto, puerto.device)
                cmb_display.addItem(texto, puerto.device)

            # Recuperar puertos guardados o usar los valores predeterminados.
            puerto_balanza = self.config_serial.value(
                "serial/puerto_balanza",
                PUERTO_BALANZA_DEFAULT,
                type=str,
            )

            puerto_display = self.config_serial.value(
                "serial/puerto_display",
                PUERTO_DISPLAY_DEFAULT,
                type=str,
            )

            # Si un puerto no está conectado, mantenerlo visible.
            for combo, guardado in (
                (cmb_balanza, puerto_balanza),
                (cmb_display, puerto_display),
            ):
                if guardado and combo.findData(guardado) == -1:
                    combo.addItem(
                        f"{guardado} - (no disponible)",
                        guardado,
                    )

                if guardado:
                    self.seleccionar_puerto(combo, guardado)

            self.log("[INFO] Puertos detectados; configuración restaurada.")

        except Exception as e:
            self.log(f"[ERROR PUERTOS] {e}")

        finally:
            cmb_balanza.blockSignals(False)
            cmb_display.blockSignals(False)

        self.guardar_configuracion_serial()

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
