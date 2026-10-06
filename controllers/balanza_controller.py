from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QMessageBox

import serial
import serial.tools.list_ports

from services.serial_balanza import SerialBalanza
from services.serial_display import SerialDisplay
from utils.parser_peso import ParserPeso

from database.database import obtener_proximo_ticket

from database.database import (
    obtener_vehiculos,
    obtener_carretas,
    obtener_conductores,
    obtener_proveedores,
    obtener_transportistas,
    obtener_concesiones,
)

from config.settings import (
    BAUDRATE_BALANZA_DEFAULT,
    BAUDRATE_DISPLAY_DEFAULT,
    INTERVALO_LECTURA_MS,
    TIMEOUT_INICIO_MS,
    SERIAL_TIMEOUT,
    PUERTO_BALANZA_DEFAULT,
    PUERTO_DISPLAY_DEFAULT,
)

# CONTROLADOR PRINCIPAL


class BalanzaController:

    def __init__(self, view):

        self.view = view

        # SERVICIOS SERIAL
        self.balanza = None
        self.display = None

        # MAESTROS
        self.vehiculos = []
        self.carretas = []
        self.conductores = []
        self.proveedores = []
        self.transportistas = []
        self.concesiones = []

        self.cargar_maestros()

        # ESTADOS
        self.balanza_comunicando = False
        self.esperando_balanza = False

        # TIMER DE LECTURA
        self.timer = QTimer()
        self.timer.setInterval(INTERVALO_LECTURA_MS)
        self.timer.timeout.connect(self.procesar_balanza)

        # TIMER DE INICIO
        self.timer_inicio = QTimer()
        self.timer_inicio.setSingleShot(True)
        self.timer_inicio.setInterval(TIMEOUT_INICIO_MS)
        self.timer_inicio.timeout.connect(self.error_inicio)

        # EVENTOS DE LA VIEW
        self.view.btn_iniciar.clicked.connect(self.iniciar)
        self.view.btn_detener.clicked.connect(self.detener)
        self.view.btn_nuevo.clicked.connect(self.nuevo_registro)

        # Puertos seriales
        self.view.configuracion.btn_actualizar.clicked.connect(self.detectar_puertos)

        self.view.act_actualizar_puertos.triggered.connect(self.detectar_puertos)

        # Datos maestros
        self.view.btn_actualizar_maestros.clicked.connect(self.actualizar_maestros)

        # DETECTAR PUERTOS AL INICIAR
        self.detectar_puertos()

    # DETECTAR PUERTOS
    def detectar_puertos(self):

        # Si el sistema está esperando comunicación,
        # no modificar los puertos.
        if self.esperando_balanza:
            return

        # Si ya está comunicando, tampoco modificar.
        if self.balanza_comunicando:
            return

        self.view.configuracion.cmb_balanza.clear()
        self.view.configuracion.cmb_display.clear()

        puertos = serial.tools.list_ports.comports()

        for puerto in puertos:

            descripcion = puerto.description or "Sin descripción"
            texto = f"{puerto.device} - " f"{descripcion}"

            # Balanza
            self.view.configuracion.cmb_balanza.addItem(texto, puerto.device)

            # Display
            self.view.configuracion.cmb_display.addItem(texto, puerto.device)

        # SELECCIONAR BALANZA POR DEFECTO
        self.seleccionar_puerto(
            self.view.configuracion.cmb_balanza, PUERTO_BALANZA_DEFAULT
        )

        # SELECCIONAR DISPLAY POR DEFECTO
        self.seleccionar_puerto(
            self.view.configuracion.cmb_display, PUERTO_DISPLAY_DEFAULT
        )
        self.log("[INFO] Puertos actualizados.")

    # SELECCIONAR PUERTO
    def seleccionar_puerto(self, combo, puerto_objetivo):

        for i in range(combo.count()):

            if combo.itemData(i) == puerto_objetivo:

                combo.setCurrentIndex(i)

                break

    # INICIAR
    def iniciar(self):

        puerto_balanza = self.view.configuracion.cmb_balanza.currentData()
        puerto_display = self.view.configuracion.cmb_display.currentData()

        # VALIDACIONES
        if not puerto_balanza:
            QMessageBox.warning(
                self.view, "Balanza", "Seleccione el puerto de la balanza."
            )
            return

        if not puerto_display:
            QMessageBox.warning(
                self.view, "Display", "Seleccione el puerto del display."
            )
            return

        if puerto_balanza == puerto_display:
            QMessageBox.warning(
                self.view,
                "Puertos",
                "La balanza y el display " "deben utilizar puertos diferentes.",
            )
            return

        try:

            # CREAR SERVICIO BALANZA
            self.balanza = SerialBalanza(
                puerto=puerto_balanza,
                baudrate=(self.view.configuracion.spin_baudrate_balanza.value()),
                timeout=SERIAL_TIMEOUT,
            )

            self.balanza.conectar()

            # CREAR SERVICIO DISPLAY
            self.display = SerialDisplay(
                puerto=puerto_display,
                baudrate=(self.view.configuracion.spin_baudrate_display.value()),
                timeout=SERIAL_TIMEOUT,
            )

            self.display.conectar()

            # ESTADOS INTERNOS
            self.esperando_balanza = True
            self.balanza_comunicando = False

            # ESTADO BALANZA
            self.view.estado_balanza(
                f"🟡 Balanza: {puerto_balanza} " f"- esperando señal...", "#b88600"
            )

            # ESTADO DISPLAY
            self.view.estado_display(
                f"🟢 Puerto display abierto: " f"{puerto_display}", "green"
            )

            # ESTADO SISTEMA
            self.view.estado_sistema(
                "🟡 Esperando comunicación " "de la balanza...", "#b88600"
            )

            self.view.lbl_peso.setText("---")

            # BLOQUEAR CONFIGURACIÓN
            self.view.btn_iniciar.setEnabled(False)
            self.view.btn_detener.setEnabled(True)
            self.view.bloquear_configuracion(True)

            # LOG
            self.log("")
            self.log("[INICIO] Sistema iniciando...")
            self.log(f"[INFO] Balanza: " f"{puerto_balanza}")
            self.log(f"[INFO] Display: " f"{puerto_display}")
            self.log("[INFO] Esperando datos " "de la balanza...")

            # INICIAR TIMERS
            self.timer.start()
            self.timer_inicio.start()

        except serial.SerialException as e:

            self.cerrar()
            self.restaurar_controles()

            self.view.estado_balanza("🔴 Error al abrir la balanza", "red")
            self.view.estado_display("🔴 Error al abrir el display", "red")
            self.view.estado_sistema("🔴 Error al abrir los puertos", "red")

            QMessageBox.critical(
                self.view,
                "Error de conexión",
                "No se pudieron abrir los puertos.\n\n" f"{e}",
            )

        except Exception as e:

            self.cerrar()
            self.restaurar_controles()
            self.view.estado_sistema("🔴 Error al iniciar", "red")
            QMessageBox.critical(self.view, "Error", str(e))

    # PROCESAR BALANZA
    def procesar_balanza(self):

        if not self.balanza:
            return

        try:

            cadena = self.balanza.leer()
            if not cadena:
                return

            self.log(f"BALANZA → {repr(cadena)}")

            # SEPARAR TRAMAS
            lineas = cadena.replace("\r", "\n").split("\n")

            for linea in lineas:

                linea = linea.strip()

                if not linea:
                    continue

                # PARSER
                peso = ParserPeso.extraer(linea)

                if peso is None:
                    continue

                # PRIMERA COMUNICACIÓN
                if not self.balanza_comunicando:

                    self.balanza_comunicando = True
                    self.esperando_balanza = False

                    self.timer_inicio.stop()

                    # BALANZA
                    self.view.estado_balanza("🟢 Balanza comunicando", "green")

                    # DISPLAY
                    self.view.estado_display("🟢 Display listo", "green")

                    # SISTEMA
                    self.view.estado_sistema("🟢 Sistema funcionando", "green")
                    self.log("[OK] Señal de balanza detectada.")
                    self.log("[OK] Sistema funcionando.")

                # MOSTRAR PESO
                self.view.mostrar_peso(peso)

                # ENVIAR DISPLAY
                self.enviar_display(peso)

        except serial.SerialException as e:

            self.log(f"[ERROR BALANZA] {e}")
            self.detener()
            QMessageBox.critical(
                self.view,
                "Error de balanza",
                "Se perdió la comunicación " "con la balanza.\n\n" f"{e}",
            )

        except Exception as e:

            self.log(f"[ERROR] {e}")

    # ENVIAR DISPLAY
    def enviar_display(self, peso):

        if not self.display:
            return

        try:

            mensaje = self.display.enviar_peso(peso)

            if mensaje:

                self.log(f"DISPLAY ← " f"{repr(mensaje)}")

        except serial.SerialException as e:

            self.log(f"[ERROR DISPLAY] {e}")

        except Exception as e:

            self.log(f"[ERROR DISPLAY] {e}")

    # TIMEOUT DE INICIO
    def error_inicio(self):

        # Si ya llegó una señal válida,
        # no hacer nada.
        if self.balanza_comunicando:
            return

        self.esperando_balanza = False

        self.timer.stop()

        self.log("")

        self.log("[ERROR] No se recibió información " "válida de la balanza.")

        self.log("[ERROR] Tiempo de espera agotado.")

        # Cerrar puertos
        self.cerrar()

        # ======================================================
        # ESTADOS
        # ======================================================

        self.view.estado_balanza(
            "🔴 No se detectó comunicación " "con la balanza", "red"
        )

        self.view.estado_display("⚪ Display detenido", "gray")

        self.view.estado_sistema("🔴 No se pudo iniciar el sistema", "red")

        # ======================================================
        # RESTAURAR CONTROLES
        # ======================================================

        self.restaurar_controles()

        # ======================================================
        # MENSAJE
        # ======================================================

        QMessageBox.warning(
            self.view,
            "No se detectó la balanza",
            "No se recibió ninguna señal válida "
            "de la balanza durante 5 segundos.\n\n"
            "Verifique:\n"
            "• Que la balanza esté encendida.\n"
            "• Que el cable serial/USB esté conectado.\n"
            "• Que el puerto seleccionado sea correcto.\n"
            "• Que la configuración sea 9600 / 8N1.",
        )

    # DETENER
    def detener(self):

        self.timer.stop()
        self.timer_inicio.stop()
        self.esperando_balanza = False
        self.balanza_comunicando = False
        self.cerrar()

        self.view.lbl_peso.setText("---")
        self.view.estado_balanza("🔴 Balanza desconectada", "red")
        self.view.estado_display("🔴 Display desconectado", "red")
        self.view.estado_sistema("Detenido", "#555")
        self.restaurar_controles()
        self.log("[SISTEMA DETENIDO]")

    # CERRAR SERVICIOS
    def cerrar(self):

        if self.balanza:

            try:
                self.balanza.cerrar()
            except Exception:
                pass

        if self.display:

            try:
                self.display.cerrar()
            except Exception:
                pass

        self.balanza = None
        self.display = None

    # RESTAURAR CONTROLES
    def restaurar_controles(self):

        self.view.btn_iniciar.setEnabled(True)
        self.view.btn_detener.setEnabled(False)
        self.view.bloquear_configuracion(False)

    # LOG
    def log(self, texto):

        self.view.log(texto)

    def nuevo_registro(self):

        proximo_ticket = obtener_proximo_ticket()

        self.view.preparar_nuevo_registro(proximo_ticket)

    def cargar_maestros(self):
        """
        Carga los datos maestros desde SQLite.
        """

        self.vehiculos = obtener_vehiculos()
        self.carretas = obtener_carretas()
        self.conductores = obtener_conductores()
        self.proveedores = obtener_proveedores()
        self.transportistas = obtener_transportistas()
        self.concesiones = obtener_concesiones()

        self.view.cargar_maestros(
            self.vehiculos,
            self.carretas,
            self.conductores,
            self.proveedores,
            self.transportistas,
            self.concesiones,
        )

    def actualizar_maestros(self):
        """
        Recarga los datos maestros desde SQLite.
        """

        self.cargar_maestros()
