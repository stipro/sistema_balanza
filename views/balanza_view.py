from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import (
    QMainWindow,
    QWidget,
    QLabel,
    QPushButton,
    QComboBox,
    QSpinBox,
    QPlainTextEdit,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QFormLayout,
    QFrame,
    QStatusBar,
)


# ==========================================================
# ESTILO GENERAL
# ==========================================================

ESTILO = """
QMainWindow,
QWidget#central {
    background-color: #f3f4f6;
}


/* ==========================================================
   MENÚ
   ========================================================== */

QMenuBar {
    background-color: #ffffff;
    border-bottom: 1px solid #d1d5db;
    padding: 2px;
}

QMenuBar::item {
    padding: 5px 12px;
    border-radius: 4px;
    background: transparent;
}

QMenuBar::item:selected {
    background-color: #2563eb;
    color: white;
}

QMenu {
    background-color: #ffffff;
    border: 1px solid #d1d5db;
    padding: 4px;
}

QMenu::item {
    padding: 6px 28px 6px 24px;
    border-radius: 4px;
}

QMenu::item:selected {
    background-color: #2563eb;
    color: white;
}

QMenu::separator {
    height: 1px;
    background: #e5e7eb;
    margin: 4px 8px;
}


/* ==========================================================
   GRUPOS
   ========================================================== */

QGroupBox {
    background-color: #ffffff;
    border: 1px solid #d1d5db;
    border-radius: 8px;
    margin-top: 12px;
    padding: 12px;
    font-weight: bold;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: #374151;
}


/* ==========================================================
   BOTONES
   ========================================================== */

QPushButton {
    border: 1px solid #d1d5db;
    border-radius: 6px;
    padding: 6px 14px;
    background-color: #ffffff;
}

QPushButton:hover {
    background-color: #eff6ff;
}

QPushButton:disabled {
    color: #9ca3af;
    background-color: #f3f4f6;
}


/* BOTÓN INICIAR */

QPushButton#btn_iniciar {
    background-color: #16a34a;
    border: none;
    color: white;
    font-size: 15px;
    font-weight: bold;
}

QPushButton#btn_iniciar:hover {
    background-color: #15803d;
}

QPushButton#btn_iniciar:disabled {
    background-color: #d1d5db;
    color: #6b7280;
}


/* BOTÓN DETENER */

QPushButton#btn_detener {
    background-color: #dc2626;
    border: none;
    color: white;
    font-size: 15px;
    font-weight: bold;
}

QPushButton#btn_detener:hover {
    background-color: #b91c1c;
}

QPushButton#btn_detener:disabled {
    background-color: #d1d5db;
    color: #6b7280;
}


/* ==========================================================
   CAMPOS
   ========================================================== */

QComboBox,
QSpinBox {
    border: 1px solid #d1d5db;
    border-radius: 6px;
    padding: 4px 8px;
    background-color: #ffffff;
    min-height: 24px;
}


/* ==========================================================
   LOG
   ========================================================== */

QPlainTextEdit {
    background-color: #111827;
    color: #d1d5db;
    border-radius: 6px;
    font-family: Consolas, "Courier New", monospace;
    font-size: 12px;
}


/* ==========================================================
   BARRA DE ESTADO
   ========================================================== */

QStatusBar {
    background-color: #ffffff;
    border-top: 1px solid #d1d5db;
}

QStatusBar::item {
    border: none;
}
"""


# ==========================================================
# VISTA PRINCIPAL
# ==========================================================

class BalanzaView(QMainWindow):

    def __init__(self):
        super().__init__()

        self.setWindowTitle("Interfaz de Balanza")
        self.setMinimumWidth(640)
        self.resize(680, 460)

        self.setStyleSheet(ESTILO)

        self.crear_menu()
        self.crear_interfaz()
        self.crear_barra_estado()

    # ======================================================
    # BARRA DE MENÚ
    # ======================================================

    def crear_menu(self):

        barra = self.menuBar()

        # --------------------------------------------------
        # ARCHIVO
        # --------------------------------------------------

        menu_archivo = barra.addMenu("&Archivo")

        self.act_salir = QAction(
            "Salir",
            self
        )

        self.act_salir.setShortcut(
            QKeySequence("Ctrl+Q")
        )

        self.act_salir.triggered.connect(
            self.close
        )

        menu_archivo.addAction(
            self.act_salir
        )

        # --------------------------------------------------
        # CONFIGURACIÓN
        # --------------------------------------------------

        menu_config = barra.addMenu(
            "&Configuración"
        )

        self.act_configuracion = QAction(
            "Mostrar configuración avanzada",
            self
        )

        self.act_configuracion.setCheckable(
            True
        )

        self.act_configuracion.setShortcut(
            QKeySequence("Ctrl+,")
        )

        menu_config.addAction(
            self.act_configuracion
        )

        menu_config.addSeparator()

        # --------------------------------------------------
        # ACTUALIZAR PUERTOS
        # --------------------------------------------------

        self.act_actualizar_puertos = QAction(
            "Actualizar puertos",
            self
        )

        self.act_actualizar_puertos.setShortcut(
            QKeySequence("F5")
        )

        menu_config.addAction(
            self.act_actualizar_puertos
        )

        # --------------------------------------------------
        # AYUDA
        # --------------------------------------------------

        menu_ayuda = barra.addMenu(
            "A&yuda"
        )

        self.act_acerca = QAction(
            "Acerca de",
            self
        )

        menu_ayuda.addAction(
            self.act_acerca
        )

        # --------------------------------------------------
        # CONEXIONES
        # --------------------------------------------------

        self.act_configuracion.triggered.connect(
            self.mostrar_configuracion
        )

    # ======================================================
    # INTERFAZ
    # ======================================================

    def crear_interfaz(self):

        central = QWidget()
        central.setObjectName("central")

        self.setCentralWidget(
            central
        )

        # --------------------------------------------------
        # TÍTULO
        # --------------------------------------------------

        self.lbl_titulo = QLabel(
            "⚖ Interfaz de Balanza"
        )

        self.lbl_titulo.setStyleSheet(
            """
            QLabel {
                font-size: 24px;
                font-weight: bold;
                color: #111827;
                padding: 4px 0;
            }
            """
        )

        # --------------------------------------------------
        # PESO
        # --------------------------------------------------

        grupo_peso = QGroupBox(
            "Peso actual"
        )

        self.lbl_peso = QLabel(
            "---"
        )

        self.lbl_peso.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )

        self.lbl_peso.setMinimumHeight(
            170
        )

        self.lbl_peso.setFrameShape(
            QFrame.Shape.NoFrame
        )

        self.lbl_peso.setStyleSheet(
            """
            QLabel {
                background-color: #0b1220;
                color: #22ff88;
                border: 3px solid #1f2937;
                border-radius: 10px;
                font-family: Consolas, "Courier New", monospace;
                font-size: 72px;
                font-weight: bold;
                padding: 10px;
            }
            """
        )

        layout_peso = QVBoxLayout()

        layout_peso.addWidget(
            self.lbl_peso
        )

        grupo_peso.setLayout(
            layout_peso
        )

        # --------------------------------------------------
        # BOTONES
        # --------------------------------------------------

        self.btn_iniciar = QPushButton(
            "▶  Iniciar"
        )

        self.btn_iniciar.setObjectName(
            "btn_iniciar"
        )

        self.btn_iniciar.setMinimumHeight(
            48
        )

        self.btn_iniciar.setCursor(
            Qt.CursorShape.PointingHandCursor
        )

        self.btn_detener = QPushButton(
            "■  Detener"
        )

        self.btn_detener.setObjectName(
            "btn_detener"
        )

        self.btn_detener.setMinimumHeight(
            48
        )

        self.btn_detener.setEnabled(
            False
        )

        self.btn_detener.setCursor(
            Qt.CursorShape.PointingHandCursor
        )

        fila_botones = QHBoxLayout()

        fila_botones.setSpacing(
            12
        )

        fila_botones.addWidget(
            self.btn_iniciar
        )

        fila_botones.addWidget(
            self.btn_detener
        )

        # --------------------------------------------------
        # PUERTOS
        # --------------------------------------------------

        grupo_puertos = QGroupBox(
            "Puertos seriales"
        )

        self.cmb_balanza = QComboBox()

        self.cmb_display = QComboBox()

        self.btn_actualizar = QPushButton(
            "🔄  Actualizar puertos"
        )

        form_puertos = QFormLayout()

        form_puertos.addRow(
            "Entrada - Balanza:",
            self.cmb_balanza
        )

        form_puertos.addRow(
            "Salida - Display:",
            self.cmb_display
        )

        form_puertos.addRow(
            "",
            self.btn_actualizar
        )

        grupo_puertos.setLayout(
            form_puertos
        )

        # --------------------------------------------------
        # CONFIGURACIÓN SERIAL
        # --------------------------------------------------

        grupo_serial = QGroupBox(
            "Configuración serial"
        )

        self.spin_baudrate_balanza = QSpinBox()

        self.spin_baudrate_balanza.setRange(
            300,
            115200
        )

        self.spin_baudrate_balanza.setValue(
            9600
        )

        self.spin_baudrate_display = QSpinBox()

        self.spin_baudrate_display.setRange(
            300,
            115200
        )

        self.spin_baudrate_display.setValue(
            9600
        )

        form_serial = QFormLayout()

        form_serial.addRow(
            "Balanza Baudrate:",
            self.spin_baudrate_balanza
        )

        form_serial.addRow(
            "Display Baudrate:",
            self.spin_baudrate_display
        )

        grupo_serial.setLayout(
            form_serial
        )

        # --------------------------------------------------
        # LOG
        # --------------------------------------------------

        grupo_log = QGroupBox(
            "Detalles técnicos"
        )

        self.txt_log = QPlainTextEdit()

        self.txt_log.setReadOnly(
            True
        )

        self.txt_log.setMinimumHeight(
            120
        )

        layout_log = QVBoxLayout()

        layout_log.addWidget(
            self.txt_log
        )

        grupo_log.setLayout(
            layout_log
        )

        # --------------------------------------------------
        # CONFIGURACIÓN AVANZADA
        # --------------------------------------------------

        self.grupo_configuracion = QWidget()

        layout_config = QVBoxLayout()

        layout_config.setContentsMargins(
            0,
            0,
            0,
            0
        )

        layout_config.setSpacing(
            10
        )

        # Puertos + Serial

        fila_superior = QHBoxLayout()

        fila_superior.setSpacing(
            10
        )

        fila_superior.addWidget(
            grupo_puertos,
            1
        )

        fila_superior.addWidget(
            grupo_serial,
            1
        )

        layout_config.addLayout(
            fila_superior
        )

        # Log

        layout_config.addWidget(
            grupo_log
        )

        self.grupo_configuracion.setLayout(
            layout_config
        )

        self.grupo_configuracion.setVisible(
            False
        )

        # --------------------------------------------------
        # CONEXIÓN DEL MENÚ CON ACTUALIZAR
        # --------------------------------------------------

        self.act_actualizar_puertos.triggered.connect(
            self.btn_actualizar.click
        )

        # --------------------------------------------------
        # LAYOUT PRINCIPAL
        # --------------------------------------------------

        layout = QVBoxLayout(
            central
        )

        layout.setContentsMargins(
            14,
            10,
            14,
            10
        )

        layout.setSpacing(
            12
        )

        layout.addWidget(
            self.lbl_titulo
        )

        layout.addWidget(
            grupo_peso
        )

        layout.addLayout(
            fila_botones
        )

        layout.addWidget(
            self.grupo_configuracion
        )

        layout.addStretch()

    # ======================================================
    # BARRA DE ESTADO
    # ======================================================

    def crear_barra_estado(self):

        barra = QStatusBar()

        barra.setSizeGripEnabled(
            False
        )

        self.setStatusBar(
            barra
        )

        # --------------------------------------------------
        # ESTADOS
        # --------------------------------------------------

        self.lbl_estado_balanza = QLabel(
            "⚪ Balanza desconectada"
        )

        self.lbl_estado_display = QLabel(
            "⚪ Display desconectado"
        )

        self.lbl_estado = QLabel(
            "Esperando..."
        )

        # --------------------------------------------------
        # ESTILO INICIAL
        # --------------------------------------------------

        for label in (
            self.lbl_estado_balanza,
            self.lbl_estado_display,
            self.lbl_estado
        ):

            label.setStyleSheet(
                """
                QLabel {
                    font-weight: bold;
                    font-size: 13px;
                    padding: 2px 10px;
                }
                """
            )

        # --------------------------------------------------
        # AGREGAR
        # --------------------------------------------------

        barra.addWidget(
            self.lbl_estado_balanza
        )

        barra.addWidget(
            self._separador()
        )

        barra.addWidget(
            self.lbl_estado_display
        )

        barra.addPermanentWidget(
            self.lbl_estado
        )

    # ======================================================
    # SEPARADOR STATUS BAR
    # ======================================================

    @staticmethod
    def _separador():

        sep = QFrame()

        sep.setFrameShape(
            QFrame.Shape.VLine
        )

        sep.setFrameShadow(
            QFrame.Shadow.Sunken
        )

        return sep

    # ======================================================
    # PESO
    # ======================================================

    def mostrar_peso(
        self,
        peso
    ):

        self.lbl_peso.setText(
            f"{peso} kg"
        )

    # ======================================================
    # CONFIGURACIÓN
    # ======================================================

    def mostrar_configuracion(
        self,
        visible
    ):

        self.grupo_configuracion.setVisible(
            visible
        )

        # Mantener sincronizado el QAction
        # sin provocar llamada recursiva.

        self.act_configuracion.blockSignals(
            True
        )

        self.act_configuracion.setChecked(
            visible
        )

        self.act_configuracion.blockSignals(
            False
        )

        self.act_configuracion.setText(
            "Ocultar configuración avanzada"
            if visible
            else "Mostrar configuración avanzada"
        )

        # Ajustar tamaño de ventana

        self.centralWidget().layout().activate()

        if visible:

            self.resize(
                self.width(),
                max(
                    self.height(),
                    700
                )
            )

        else:

            self.resize(
                self.width(),
                460
            )

    # ======================================================
    # ESTADOS
    # ======================================================

    def _estilo_estado(
        self,
        label,
        texto,
        color,
        size=13
    ):

        label.setText(
            texto
        )

        label.setStyleSheet(
            f"""
            QLabel {{
                font-weight: bold;
                font-size: {size}px;
                padding: 2px 10px;
                color: {color};
            }}
            """
        )

    # ------------------------------------------------------
    # ESTADO BALANZA
    # ------------------------------------------------------

    def estado_balanza(
        self,
        texto,
        color
    ):

        self._estilo_estado(
            self.lbl_estado_balanza,
            texto,
            color
        )

    # ------------------------------------------------------
    # ESTADO DISPLAY
    # ------------------------------------------------------

    def estado_display(
        self,
        texto,
        color
    ):

        self._estilo_estado(
            self.lbl_estado_display,
            texto,
            color
        )

    # ------------------------------------------------------
    # ESTADO SISTEMA
    # ------------------------------------------------------

    def estado_sistema(
        self,
        texto,
        color
    ):

        self._estilo_estado(
            self.lbl_estado,
            texto,
            color,
            size=14
        )

    # ======================================================
    # CONTROLES
    # ======================================================

    def bloquear_configuracion(
        self,
        bloquear=True
    ):

        habilitado = not bloquear

        # --------------------------------------------------
        # CONTROLES DE PUERTOS
        # --------------------------------------------------

        self.cmb_balanza.setEnabled(
            habilitado
        )

        self.cmb_display.setEnabled(
            habilitado
        )

        self.btn_actualizar.setEnabled(
            habilitado
        )

        # --------------------------------------------------
        # CONFIGURACIÓN SERIAL
        # --------------------------------------------------

        self.spin_baudrate_balanza.setEnabled(
            habilitado
        )

        self.spin_baudrate_display.setEnabled(
            habilitado
        )

        # --------------------------------------------------
        # ACCIONES DEL MENÚ
        # --------------------------------------------------

        self.act_configuracion.setEnabled(
            habilitado
        )

        self.act_actualizar_puertos.setEnabled(
            habilitado
        )

    # ======================================================
    # LOG
    # ======================================================

    def log(
        self,
        texto
    ):

        self.txt_log.appendPlainText(
            texto
        )

        scrollbar = (
            self.txt_log.verticalScrollBar()
        )

        scrollbar.setValue(
            scrollbar.maximum()
        )

    # ======================================================
    # CERRAR VENTANA
    # ======================================================

    def closeEvent(
        self,
        event
    ):

        # El controller puede encargarse de detener
        # mediante su propia conexión si la tiene.

        event.accept()