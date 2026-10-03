import sys
import serial
import serial.tools.list_ports

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import (
    QApplication,
    QWidget,
    QLabel,
    QPushButton,
    QComboBox,
    QSpinBox,
    QPlainTextEdit,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QMessageBox,
)


class InterfazBalanza(QWidget):

    def __init__(self):
        super().__init__()

        # ==========================================================
        # SERIAL
        # ==========================================================

        self.balanza = None
        self.display = None

        # ==========================================================
        # ESTADOS
        # ==========================================================

        self.esperando_balanza = False
        self.balanza_comunicando = False

        # ==========================================================
        # TIMER PRINCIPAL
        # ==========================================================

        self.timer = QTimer(self)
        self.timer.setInterval(400)
        self.timer.timeout.connect(self.leer_balanza)

        # ==========================================================
        # TIMER DE INICIO
        # ==========================================================
        # Espera máximo 5 segundos para recibir
        # una trama válida de la balanza.
        # ==========================================================

        self.timer_inicio = QTimer(self)
        self.timer_inicio.setSingleShot(True)
        self.timer_inicio.setInterval(5000)
        self.timer_inicio.timeout.connect(self.error_inicio)

        # ==========================================================
        # INTERFAZ
        # ==========================================================

        self.init_ui()

        # ==========================================================
        # DETECTAR PUERTOS
        # ==========================================================

        self.detectar_puertos()

    # ==============================================================
    # INTERFAZ
    # ==============================================================

    def init_ui(self):

        self.setWindowTitle("Interfaz de Balanza")

        self.resize(750, 600)

        # ==========================================================
        # TÍTULO
        # ==========================================================

        self.lbl_titulo = QLabel("⚖ Interfaz de Balanza")

        self.lbl_titulo.setStyleSheet("""
            QLabel {
                font-size: 24px;
                font-weight: bold;
            }
        """)

        # ==========================================================
        # BOTÓN CONFIGURACIÓN
        # ==========================================================

        self.btn_configuracion = QPushButton("⚙ Configuración")

        self.btn_configuracion.setCheckable(True)

        self.btn_configuracion.clicked.connect(self.alternar_configuracion)

        self.btn_configuracion.setStyleSheet("""
            QPushButton {
                padding: 8px 14px;
                font-weight: bold;
            }
        """)

        # ==========================================================
        # CABECERA
        # ==========================================================

        fila_superior = QHBoxLayout()

        fila_superior.addWidget(self.lbl_titulo)

        fila_superior.addStretch()

        fila_superior.addWidget(self.btn_configuracion)

        # ==========================================================
        # PESO
        # ==========================================================

        grupo_peso = QGroupBox("Peso actual")

        self.lbl_peso = QLabel("---")

        self.lbl_peso.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.lbl_peso.setMinimumHeight(180)

        self.lbl_peso.setStyleSheet("""
            QLabel {
                font-size: 64px;
                font-weight: bold;
                padding: 25px;
            }
        """)

        layout_peso = QVBoxLayout()

        layout_peso.addWidget(self.lbl_peso)

        grupo_peso.setLayout(layout_peso)

        # ==========================================================
        # ESTADOS
        # ==========================================================

        self.lbl_estado_balanza = QLabel("⚪ Balanza desconectada")

        self.lbl_estado_balanza.setStyleSheet("""
            QLabel {
                font-weight: bold;
                font-size: 15px;
            }
        """)

        self.lbl_estado_display = QLabel("⚪ Display desconectado")

        self.lbl_estado_display.setStyleSheet("""
            QLabel {
                font-weight: bold;
                font-size: 15px;
            }
        """)

        self.lbl_estado = QLabel("Esperando...")

        self.lbl_estado.setStyleSheet("""
            QLabel {
                font-weight: bold;
                font-size: 16px;
            }
        """)

        # ==========================================================
        # BOTONES PRINCIPALES
        # ==========================================================

        self.btn_iniciar = QPushButton("▶ Iniciar")

        self.btn_iniciar.setMinimumHeight(45)

        self.btn_iniciar.clicked.connect(self.iniciar)

        self.btn_detener = QPushButton("■ Detener")

        self.btn_detener.setMinimumHeight(45)

        self.btn_detener.clicked.connect(self.detener)

        self.btn_detener.setEnabled(False)

        fila_botones_principales = QHBoxLayout()

        fila_botones_principales.addWidget(self.btn_iniciar)

        fila_botones_principales.addWidget(self.btn_detener)

        # ==========================================================
        # PUERTOS
        # ==========================================================

        grupo_puertos = QGroupBox("Puertos seriales")

        self.cmb_balanza = QComboBox()

        self.cmb_display = QComboBox()

        self.btn_actualizar = QPushButton("🔄 Actualizar puertos")

        self.btn_actualizar.clicked.connect(self.detectar_puertos)

        # ----------------------------------------------------------
        # BALANZA
        # ----------------------------------------------------------

        fila_balanza = QHBoxLayout()

        fila_balanza.addWidget(QLabel("Entrada - Balanza:"))

        fila_balanza.addWidget(self.cmb_balanza, 1)

        # ----------------------------------------------------------
        # DISPLAY
        # ----------------------------------------------------------

        fila_display = QHBoxLayout()

        fila_display.addWidget(QLabel("Salida - Display:"))

        fila_display.addWidget(self.cmb_display, 1)

        # ----------------------------------------------------------
        # LAYOUT PUERTOS
        # ----------------------------------------------------------

        layout_puertos = QVBoxLayout()

        layout_puertos.addLayout(fila_balanza)

        layout_puertos.addLayout(fila_display)

        layout_puertos.addWidget(self.btn_actualizar)

        grupo_puertos.setLayout(layout_puertos)

        # ==========================================================
        # CONFIGURACIÓN SERIAL
        # ==========================================================

        grupo_config = QGroupBox("Configuración serial")

        self.spin_baudrate_balanza = QSpinBox()

        self.spin_baudrate_balanza.setRange(300, 115200)

        self.spin_baudrate_balanza.setValue(9600)

        self.spin_baudrate_display = QSpinBox()

        self.spin_baudrate_display.setRange(300, 115200)

        self.spin_baudrate_display.setValue(9600)

        fila_config = QHBoxLayout()

        fila_config.addWidget(QLabel("Balanza Baudrate:"))

        fila_config.addWidget(self.spin_baudrate_balanza)

        fila_config.addSpacing(20)

        fila_config.addWidget(QLabel("Display Baudrate:"))

        fila_config.addWidget(self.spin_baudrate_display)

        fila_config.addStretch()

        grupo_config.setLayout(fila_config)

        # ==========================================================
        # COMUNICACIÓN / LOG
        # ==========================================================

        grupo_trama = QGroupBox("Detalles técnicos")

        self.txt_log = QPlainTextEdit()

        self.txt_log.setReadOnly(True)

        self.txt_log.setMinimumHeight(180)

        layout_log = QVBoxLayout()

        layout_log.addWidget(self.txt_log)

        grupo_trama.setLayout(layout_log)

        # ==========================================================
        # GRUPO DE CONFIGURACIÓN
        # ==========================================================

        self.grupo_configuracion = QGroupBox("Configuración avanzada")

        layout_configuracion = QVBoxLayout()

        layout_configuracion.addWidget(grupo_puertos)

        layout_configuracion.addWidget(grupo_config)

        layout_configuracion.addWidget(grupo_trama)

        self.grupo_configuracion.setLayout(layout_configuracion)

        # OCULTO POR DEFECTO

        self.grupo_configuracion.setVisible(False)

        # ==========================================================
        # LAYOUT PRINCIPAL
        # ==========================================================

        layout = QVBoxLayout()

        layout.setSpacing(12)

        layout.addLayout(fila_superior)

        layout.addWidget(grupo_peso)

        layout.addWidget(self.lbl_estado_balanza)

        layout.addWidget(self.lbl_estado_display)

        layout.addWidget(self.lbl_estado)

        layout.addLayout(fila_botones_principales)

        layout.addWidget(self.grupo_configuracion)

        self.setLayout(layout)

    # ==============================================================
    # CONFIGURACIÓN
    # ==============================================================

    def alternar_configuracion(self):

        visible = self.btn_configuracion.isChecked()

        self.grupo_configuracion.setVisible(visible)

        if visible:

            self.btn_configuracion.setText("✕ Ocultar configuración")

        else:

            self.btn_configuracion.setText("⚙ Configuración")

    # ==============================================================
    # DETECTAR PUERTOS
    # ==============================================================

    def detectar_puertos(self):

        # No permitir actualizar mientras está funcionando

        if self.balanza_comunicando or self.esperando_balanza:

            return

        self.cmb_balanza.clear()

        self.cmb_display.clear()

        puertos = serial.tools.list_ports.comports()

        for puerto in puertos:

            descripcion = puerto.description or "Sin descripción"

            texto = f"{puerto.device} - " f"{descripcion}"

            self.cmb_balanza.addItem(texto, puerto.device)

            self.cmb_display.addItem(texto, puerto.device)

        # ==========================================================
        # SELECCIONAR COM5 COMO BALANZA
        # ==========================================================

        for i in range(self.cmb_balanza.count()):

            if self.cmb_balanza.itemData(i) == "COM5":

                self.cmb_balanza.setCurrentIndex(i)

                break

        # ==========================================================
        # SELECCIONAR COM6 COMO DISPLAY
        # ==========================================================

        for i in range(self.cmb_display.count()):

            if self.cmb_display.itemData(i) == "COM6":

                self.cmb_display.setCurrentIndex(i)

                break

        self.log("[INFO] Puertos actualizados.")

    # ==============================================================
    # INICIAR
    # ==============================================================

    def iniciar(self):

        puerto_balanza = self.cmb_balanza.currentData()

        puerto_display = self.cmb_display.currentData()

        # ==========================================================
        # VALIDAR BALANZA
        # ==========================================================

        if not puerto_balanza:

            QMessageBox.warning(self, "Balanza", "Seleccione el puerto de la balanza.")

            return

        # ==========================================================
        # VALIDAR DISPLAY
        # ==========================================================

        if not puerto_display:

            QMessageBox.warning(self, "Display", "Seleccione el puerto del display.")

            return

        # ==========================================================
        # VALIDAR PUERTOS DIFERENTES
        # ==========================================================

        if puerto_balanza == puerto_display:

            QMessageBox.warning(
                self,
                "Puertos",
                "La balanza y el display " "deben utilizar puertos diferentes.",
            )

            return

        try:

            # ======================================================
            # BALANZA
            # ======================================================

            self.balanza = serial.Serial(
                port=puerto_balanza,
                baudrate=(self.spin_baudrate_balanza.value()),
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0.1,
            )

            # Igual que el programa original

            self.balanza.dtr = True
            self.balanza.rts = True

            # ======================================================
            # DISPLAY
            # ======================================================

            self.display = serial.Serial(
                port=puerto_display,
                baudrate=(self.spin_baudrate_display.value()),
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0.1,
            )

            # Igual que el programa original

            self.display.dtr = True
            self.display.rts = True

            # ======================================================
            # LIMPIAR BUFFERS
            # ======================================================

            self.balanza.reset_input_buffer()

            self.display.reset_input_buffer()

            # ======================================================
            # ESTADO INICIAL
            # ======================================================

            self.esperando_balanza = True

            self.balanza_comunicando = False

            # ======================================================
            # BALANZA
            # ======================================================

            self.lbl_estado_balanza.setText(
                f"🟡 Balanza: {puerto_balanza} " f"- esperando señal..."
            )

            self.lbl_estado_balanza.setStyleSheet("""
                QLabel {
                    font-weight: bold;
                    font-size: 15px;
                    color: #b88600;
                }
            """)

            # ======================================================
            # DISPLAY
            # ======================================================

            self.lbl_estado_display.setText(
                f"🟢 Puerto display abierto: " f"{puerto_display}"
            )

            self.lbl_estado_display.setStyleSheet("""
                QLabel {
                    font-weight: bold;
                    font-size: 15px;
                    color: green;
                }
            """)

            # ======================================================
            # ESTADO GENERAL
            # ======================================================

            self.lbl_estado.setText("🟡 Esperando comunicación " "de la balanza...")

            self.lbl_estado.setStyleSheet("""
                QLabel {
                    font-weight: bold;
                    font-size: 16px;
                    color: #b88600;
                }
            """)

            self.lbl_peso.setText("---")

            # ======================================================
            # BLOQUEAR CONFIGURACIÓN
            # ======================================================

            self.btn_iniciar.setEnabled(False)

            self.btn_detener.setEnabled(True)

            self.btn_configuracion.setEnabled(False)

            self.cmb_balanza.setEnabled(False)

            self.cmb_display.setEnabled(False)

            self.btn_actualizar.setEnabled(False)

            self.spin_baudrate_balanza.setEnabled(False)

            self.spin_baudrate_display.setEnabled(False)

            # ======================================================
            # LOG
            # ======================================================

            self.log("")

            self.log("[INICIO] Sistema iniciando...")

            self.log(f"[INFO] Balanza: " f"{puerto_balanza}")

            self.log(f"[INFO] Display: " f"{puerto_display}")

            self.log("[INFO] Esperando datos " "de la balanza...")

            # ======================================================
            # INICIAR LECTURA
            # ======================================================

            self.timer.start()

            # ======================================================
            # INICIAR TIEMPO DE ESPERA
            # ======================================================

            self.timer_inicio.start()

        except serial.SerialException as e:

            self.cerrar_puertos()

            self.lbl_estado.setText("🔴 Error al abrir los puertos")

            self.lbl_estado.setStyleSheet("""
                QLabel {
                    font-weight: bold;
                    font-size: 16px;
                    color: red;
                }
            """)

            self.restaurar_controles()

            QMessageBox.critical(
                self,
                "Error de conexión",
                "No se pudieron abrir los puertos.\n\n" f"{e}",
            )

        except Exception as e:

            self.cerrar_puertos()

            self.restaurar_controles()

            QMessageBox.critical(self, "Error", str(e))

    # ==============================================================
    # ERROR DE INICIO
    # ==============================================================

    def error_inicio(self):

        # ==========================================================
        # SI YA HAY COMUNICACIÓN, NO HACER NADA
        # ==========================================================

        if self.balanza_comunicando:

            return

        self.esperando_balanza = False

        self.log("")

        self.log("[ERROR] No se recibió información " "válida de la balanza.")

        self.log("[ERROR] Tiempo de espera agotado.")

        # ==========================================================
        # DETENER TIMER PRINCIPAL
        # ==========================================================

        self.timer.stop()

        # ==========================================================
        # CERRAR PUERTOS
        # ==========================================================

        self.cerrar_puertos()

        # ==========================================================
        # ESTADO BALANZA
        # ==========================================================

        self.lbl_estado_balanza.setText(
            "🔴 No se detectó comunicación " "con la balanza"
        )

        self.lbl_estado_balanza.setStyleSheet("""
            QLabel {
                font-weight: bold;
                font-size: 15px;
                color: red;
            }
        """)

        # ==========================================================
        # ESTADO DISPLAY
        # ==========================================================

        self.lbl_estado_display.setText("⚪ Display detenido")

        self.lbl_estado_display.setStyleSheet("""
            QLabel {
                font-weight: bold;
                font-size: 15px;
                color: gray;
            }
        """)

        # ==========================================================
        # ESTADO GENERAL
        # ==========================================================

        self.lbl_estado.setText("🔴 No se pudo iniciar el sistema")

        self.lbl_estado.setStyleSheet("""
            QLabel {
                font-weight: bold;
                font-size: 16px;
                color: red;
            }
        """)

        # ==========================================================
        # RESTAURAR CONTROLES
        # ==========================================================

        self.restaurar_controles()

        # ==========================================================
        # MENSAJE AL USUARIO
        # ==========================================================

        QMessageBox.warning(
            self,
            "No se detectó la balanza",
            "No se recibió ninguna señal válida "
            "de la balanza durante 5 segundos.\n\n"
            "Verifique:\n"
            "• Que la balanza esté encendida.\n"
            "• Que el cable serial/USB esté conectado.\n"
            "• Que el puerto seleccionado sea correcto.\n"
            "• Que la configuración sea 9600 / 8N1.",
        )

    # ==============================================================
    # LEER BALANZA
    # ==============================================================

    def leer_balanza(self):

        if not self.balanza:

            return

        if not self.balanza.is_open:

            return

        try:

            cantidad = self.balanza.in_waiting

            if cantidad <= 0:

                return

            datos = self.balanza.read(cantidad)

            if not datos:

                return

            cadena = datos.decode("ascii", errors="ignore")

            # ======================================================
            # MOSTRAR TRAMA RECIBIDA
            # ======================================================

            self.log(f"BALANZA → {repr(cadena)}")

            # ======================================================
            # SEPARAR POSIBLES TRAMAS
            # ======================================================

            lineas = cadena.replace("\r", "\n").split("\n")

            for linea in lineas:

                linea = linea.strip()

                if not linea:

                    continue

                # ==================================================
                # VALIDAR INICIO
                # ==================================================

                if not linea.startswith("S"):

                    continue

                # ==================================================
                # EXTRAER PESO
                # ==================================================

                peso = self.extraer_peso(linea)

                if peso is None:

                    continue

                # ==================================================
                # PRIMERA COMUNICACIÓN VÁLIDA
                # ==================================================

                if not self.balanza_comunicando:

                    self.balanza_comunicando = True

                    self.esperando_balanza = False

                    # Detener timeout inicial

                    self.timer_inicio.stop()

                    # ------------------------------------------------
                    # BALANZA
                    # ------------------------------------------------

                    self.lbl_estado_balanza.setText("🟢 Balanza comunicando")

                    self.lbl_estado_balanza.setStyleSheet("""
                        QLabel {
                            font-weight: bold;
                            font-size: 15px;
                            color: green;
                        }
                    """)

                    # ------------------------------------------------
                    # DISPLAY
                    # ------------------------------------------------

                    self.lbl_estado_display.setText("🟢 Display listo")

                    self.lbl_estado_display.setStyleSheet("""
                        QLabel {
                            font-weight: bold;
                            font-size: 15px;
                            color: green;
                        }
                    """)

                    # ------------------------------------------------
                    # SISTEMA
                    # ------------------------------------------------

                    self.lbl_estado.setText("🟢 Sistema funcionando")

                    self.lbl_estado.setStyleSheet("""
                        QLabel {
                            font-weight: bold;
                            font-size: 16px;
                            color: green;
                        }
                    """)

                    self.log("[OK] Señal de balanza detectada.")

                    self.log("[OK] Sistema funcionando.")

                # ==================================================
                # MOSTRAR PESO
                # ==================================================

                self.lbl_peso.setText(f"{peso} kg")

                # ==================================================
                # ENVIAR DISPLAY
                # ==================================================

                self.enviar_display(peso)

        except serial.SerialException as e:

            self.log(f"[ERROR BALANZA] {e}")

            self.detener()

            QMessageBox.critical(
                self,
                "Error de balanza",
                "Se perdió la comunicación " "con la balanza.\n\n" f"{e}",
            )

        except Exception as e:

            self.log(f"[ERROR] {e}")

    # ==============================================================
    # EXTRAER PESO
    # ==============================================================

    def extraer_peso(self, trama):

        try:

            trama = trama.strip()

            # ======================================================
            # DEBE COMENZAR CON S
            # ======================================================

            if not trama.startswith("S"):

                return None

            # ======================================================
            # FORMATO ORIGINAL
            # ======================================================
            #
            # S     012345
            #
            # El programa original utilizaba:
            #
            # cadena.Substring(6, 6)
            #
            # ======================================================

            if len(trama) >= 12:

                peso_original = trama[6:12].strip()

                if peso_original:

                    peso_limpio = peso_original.replace(".", "").replace("-", "")

                    if peso_limpio.isdigit():

                        return peso_original

            # ======================================================
            # FORMATO:
            #
            # S          0 kg
            #
            # ======================================================

            partes = trama.split()

            if len(partes) >= 2:

                peso = partes[1].strip()

                peso_limpio = peso.replace(".", "").replace("-", "")

                if peso_limpio.isdigit():

                    return peso

            return None

        except Exception:

            return None

    # ==============================================================
    # ENVIAR PESO AL DISPLAY
    # ==============================================================

    def enviar_display(self, peso):

        if not self.display:

            return

        if not self.display.is_open:

            return

        try:

            peso = str(peso).strip()

            if not peso:

                return

            # ======================================================
            # LÓGICA ACTUAL DEL PROGRAMA ORIGINAL
            # ======================================================

            peso_invertido = peso[::-1]

            mensaje = "= " + peso_invertido

            # ======================================================
            # ENVIAR
            # ======================================================

            self.display.write(mensaje.encode("ascii"))

            self.display.flush()

            self.log(f"DISPLAY ← {repr(mensaje)}")

        except serial.SerialException as e:

            self.log(f"[ERROR DISPLAY] {e}")

        except Exception as e:

            self.log(f"[ERROR DISPLAY] {e}")

    # ==============================================================
    # RESTAURAR CONTROLES
    # ==============================================================

    def restaurar_controles(self):

        self.btn_iniciar.setEnabled(True)

        self.btn_detener.setEnabled(False)

        self.btn_configuracion.setEnabled(True)

        self.btn_actualizar.setEnabled(True)

        self.cmb_balanza.setEnabled(True)

        self.cmb_display.setEnabled(True)

        self.spin_baudrate_balanza.setEnabled(True)

        self.spin_baudrate_display.setEnabled(True)

    # ==============================================================
    # DETENER
    # ==============================================================

    def detener(self):

        # ==========================================================
        # DETENER TIMERS
        # ==========================================================

        self.timer.stop()

        self.timer_inicio.stop()

        # ==========================================================
        # REINICIAR ESTADOS
        # ==========================================================

        self.esperando_balanza = False

        self.balanza_comunicando = False

        # ==========================================================
        # CERRAR PUERTOS
        # ==========================================================

        self.cerrar_puertos()

        # ==========================================================
        # ESTADO BALANZA
        # ==========================================================

        self.lbl_estado_balanza.setText("🔴 Balanza desconectada")

        self.lbl_estado_balanza.setStyleSheet("""
            QLabel {
                font-weight: bold;
                font-size: 15px;
                color: red;
            }
        """)

        # ==========================================================
        # ESTADO DISPLAY
        # ==========================================================

        self.lbl_estado_display.setText("🔴 Display desconectado")

        self.lbl_estado_display.setStyleSheet("""
            QLabel {
                font-weight: bold;
                font-size: 15px;
                color: red;
            }
        """)

        # ==========================================================
        # ESTADO GENERAL
        # ==========================================================

        self.lbl_estado.setText("Detenido")

        self.lbl_estado.setStyleSheet("""
            QLabel {
                font-weight: bold;
                font-size: 16px;
                color: #555;
            }
        """)

        # ==========================================================
        # PESO
        # ==========================================================

        self.lbl_peso.setText("---")

        # ==========================================================
        # RESTAURAR CONTROLES
        # ==========================================================

        self.restaurar_controles()

        self.log("[SISTEMA DETENIDO]")

    # ==============================================================
    # CERRAR PUERTOS
    # ==============================================================

    def cerrar_puertos(self):

        # ==========================================================
        # BALANZA
        # ==========================================================

        if self.balanza:

            try:

                if self.balanza.is_open:

                    self.balanza.close()

            except Exception:

                pass

        # ==========================================================
        # DISPLAY
        # ==========================================================

        if self.display:

            try:

                if self.display.is_open:

                    self.display.close()

            except Exception:

                pass

        # ==========================================================
        # LIBERAR REFERENCIAS
        # ==========================================================

        self.balanza = None

        self.display = None

    # ==============================================================
    # LOG
    # ==============================================================

    def log(self, texto):

        self.txt_log.appendPlainText(texto)

        scrollbar = self.txt_log.verticalScrollBar()

        scrollbar.setValue(scrollbar.maximum())

    # ==============================================================
    # CERRAR VENTANA
    # ==============================================================

    def closeEvent(self, event):

        self.detener()

        event.accept()


# ==================================================================
# EJECUTAR
# ==================================================================

if __name__ == "__main__":

    app = QApplication(sys.argv)

    ventana = InterfazBalanza()

    ventana.show()

    sys.exit(app.exec())
