from PyQt6.QtWidgets import (
    QDialog,
    QPushButton,
    QComboBox,
    QSpinBox,
    QPlainTextEdit,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QFormLayout,
)

from config.settings import (
    BAUDRATE_BALANZA_DEFAULT,
    BAUDRATE_DISPLAY_DEFAULT,
)


class ConfiguracionView(QDialog):

    def __init__(self, parent=None):

        super().__init__(parent)

        self.setWindowTitle("Configuración avanzada")
        self.resize(780, 520)

        self._crear_interfaz()

    def _crear_interfaz(self):

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(10)

        # PUERTOS
        grupo_puertos = QGroupBox("Puertos seriales")

        form_puertos = QFormLayout(grupo_puertos)

        self.cmb_balanza = QComboBox()
        self.cmb_display = QComboBox()

        self.btn_actualizar = QPushButton("🔄  Actualizar puertos")

        form_puertos.addRow("Entrada - Balanza:", self.cmb_balanza)

        form_puertos.addRow("Salida - Display:", self.cmb_display)

        form_puertos.addRow("", self.btn_actualizar)

        # CONFIGURACIÓN SERIAL
        grupo_serial = QGroupBox("Configuración serial")

        form_serial = QFormLayout(grupo_serial)

        self.spin_baudrate_balanza = QSpinBox()
        self.spin_baudrate_balanza.setRange(300, 115200)
        self.spin_baudrate_balanza.setValue(BAUDRATE_BALANZA_DEFAULT)

        self.spin_baudrate_display = QSpinBox()
        self.spin_baudrate_display.setRange(300, 115200)
        self.spin_baudrate_display.setValue(BAUDRATE_DISPLAY_DEFAULT)

        form_serial.addRow("Balanza Baudrate:", self.spin_baudrate_balanza)

        form_serial.addRow("Display Baudrate:", self.spin_baudrate_display)

        fila = QHBoxLayout()
        fila.setSpacing(10)

        fila.addWidget(grupo_puertos, 1)

        fila.addWidget(grupo_serial, 1)

        layout.addLayout(fila)

        # LOG
        grupo_log = QGroupBox("Detalles técnicos")

        lay_log = QVBoxLayout(grupo_log)

        self.txt_log = QPlainTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setMaximumBlockCount(1000)
        self.txt_log.setMinimumHeight(150)

        lay_log.addWidget(self.txt_log)

        layout.addWidget(grupo_log, 1)

    # CONTROLES
    def bloquear_configuracion(self, bloquear=True):

        habilitado = not bloquear

        self.cmb_balanza.setEnabled(habilitado)

        self.cmb_display.setEnabled(habilitado)

        self.btn_actualizar.setEnabled(habilitado)

        self.spin_baudrate_balanza.setEnabled(habilitado)

        self.spin_baudrate_display.setEnabled(habilitado)

    # LOG
    def log(self, texto):

        self.txt_log.appendPlainText(texto)

        scrollbar = self.txt_log.verticalScrollBar()

        scrollbar.setValue(scrollbar.maximum())
