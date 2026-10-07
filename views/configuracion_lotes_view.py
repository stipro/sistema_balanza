from PyQt6.QtWidgets import (
    QDialog,
    QSpinBox,
    QPushButton,
    QLabel,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QFormLayout,
)
from PyQt6.QtCore import Qt


class ConfiguracionLotesView(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle("Configuración de lotes")
        self.setModal(True)
        self.resize(450, 320)

        self.crear_interfaz()

    def crear_interfaz(self):

        # TÍTULO
        self.lbl_titulo = QLabel("Configuración de lotes")
        self.lbl_titulo.setObjectName("titulo")

        self.lbl_descripcion = QLabel(
            "Configure el número correlativo inicial para "
            "la generación automática de lotes."
        )
        self.lbl_descripcion.setWordWrap(True)

        # AVISO
        self.lbl_aviso = QLabel()
        self.lbl_aviso.setWordWrap(True)
        self.lbl_aviso.setObjectName("aviso")
        self.lbl_aviso.hide()

        # CORRELATIVO
        self.spin_correlativo = QSpinBox()
        self.spin_correlativo.setRange(1, 999999999)
        self.spin_correlativo.setValue(1500)
        self.spin_correlativo.setMinimumWidth(180)

        # PREFIJO
        self.txt_prefijo = QLabel("—")
        self.txt_prefijo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.txt_prefijo.setMinimumWidth(180)
        self.txt_prefijo.setObjectName("campo_solo_lectura")

        # PRÓXIMO LOTE
        self.txt_proximo_lote = QLabel("—")
        self.txt_proximo_lote.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.txt_proximo_lote.setMinimumWidth(180)
        self.txt_proximo_lote.setObjectName("campo_lote")

        # FORMULARIO
        formulario = QFormLayout()
        formulario.setSpacing(12)

        formulario.addRow("Próximo correlativo:", self.spin_correlativo)

        formulario.addRow("Prefijo automático:", self.txt_prefijo)

        formulario.addRow("Próximo lote:", self.txt_proximo_lote)

        grupo = QGroupBox("Configuración")
        grupo.setLayout(formulario)

        # BOTONES
        self.btn_guardar = QPushButton("💾  Guardar configuración")
        self.btn_cancelar = QPushButton("Cancelar")

        self.btn_guardar.setDefault(True)

        botones = QHBoxLayout()
        botones.addStretch()
        botones.addWidget(self.btn_cancelar)
        botones.addWidget(self.btn_guardar)

        # LAYOUT PRINCIPAL
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        layout.addWidget(self.lbl_titulo)
        layout.addWidget(self.lbl_descripcion)
        layout.addWidget(self.lbl_aviso)
        layout.addWidget(grupo)
        layout.addStretch()
        layout.addLayout(botones)

        # EVENTOS
        self.spin_correlativo.valueChanged.connect(self.actualizar_preview)

        self.btn_cancelar.clicked.connect(self.reject)

        self.actualizar_preview()

    # PREVISUALIZACIÓN
    def actualizar_preview(self):

        correlativo = self.spin_correlativo.value()

        prefijo = self.obtener_prefijo_actual()

        self.txt_prefijo.setText(prefijo)

        self.txt_proximo_lote.setText(f"{prefijo}-{correlativo}")

    # PREFIJO AUTOMÁTICO
    def obtener_prefijo_actual(self):

        from datetime import datetime

        fecha = datetime.now()

        ultimo_digito_anio = str(fecha.year)[-1]
        mes = f"{fecha.month:02d}"

        return f"{ultimo_digito_anio}{mes}"

    # ESTADO DE CONFIGURACIÓN
    def mostrar_sin_configuracion(self):

        self.lbl_aviso.setText(
            "⚠️ No se ha configurado ningún correlativo " "para los lotes."
        )

        self.lbl_aviso.show()

    def ocultar_aviso(self):

        self.lbl_aviso.clear()
        self.lbl_aviso.hide()

    # CARGAR CONFIGURACIÓN EXISTENTE
    def cargar_correlativo(self, correlativo):

        if correlativo is None:
            self.mostrar_sin_configuracion()
            return

        self.spin_correlativo.setValue(correlativo)
        self.ocultar_aviso()
