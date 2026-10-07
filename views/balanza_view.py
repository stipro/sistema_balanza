from PyQt6.QtCore import (
    Qt,
    pyqtSignal,
    QStringListModel,
    QTimer,
)
from PyQt6.QtGui import QAction, QKeySequence, QColor
from PyQt6.QtWidgets import (
    QMainWindow,
    QWidget,
    QScrollArea,
    QLabel,
    QPushButton,
    QLineEdit,
    QCompleter,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QAbstractItemView,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QGroupBox,
    QFrame,
    QStatusBar,
    QMessageBox,
)

from config.settings import (
    APP_NAME,
)
from pathlib import Path
import sys

from views.configuracion_view import ConfiguracionView
from views.configuracion_lotes_view import ConfiguracionLotesView
from views.combo_busqueda import ComboBusqueda


def ruta_recurso(ruta):
    """
    Obtiene la ruta de un recurso tanto en desarrollo
    como cuando la aplicación está empaquetada.
    """

    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS)
    else:
        base = Path(__file__).resolve().parent.parent

    return base / ruta


def cargar_estilo():

    ruta = ruta_recurso("styles/balanza.qss")

    with open(ruta, "r", encoding="utf-8") as archivo:

        return archivo.read()


# (texto, fondo, color texto, borde)
ESTADOS_OPERACION = {
    "proceso": ("● EN PROCESO", "#eff6ff", "#1d4ed8", "#bfdbfe"),
    "pendiente": ("● PENDIENTE", "#fffbeb", "#b45309", "#fde68a"),
    "completo": ("● COMPLETO", "#f0fdf4", "#15803d", "#bbf7d0"),
    "error": ("● ERROR", "#fef2f2", "#b91c1c", "#fecaca"),
}


# VISTA PRINCIPAL
class BalanzaView(QMainWindow):

    # Se emite al cerrar la ventana (el controller puede conectarse
    # para cerrar los puertos de forma ordenada)
    cerrando = pyqtSignal()

    def __init__(self):

        super().__init__()

        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(1000, 600)
        self.resize(1180, 720)

        self.setStyleSheet(cargar_estilo())

        # Datos maestros (vacíos hasta que el controller los cargue)
        self.maestros = {}

        # Selecciones internas
        # (se definen ANTES de crear la interfaz porque los combos
        # pueden disparar señales al construirse)
        self.vehiculo_seleccionado = None
        self.carreta_seleccionada = None

        self.proveedor_seleccionado = None
        self.completer_proveedor = None
        self.completer_ruc_proveedor = None

        self.conductor_seleccionado = None
        self.completer_chofer = None
        self.completer_brevete = None

        self.transportista_seleccionado = None
        self.completer_transportista = None
        self.completer_ruc_transportista = None

        self.concesion_seleccionada = None
        self.completer_concesion = None
        self.completer_codigo = None

        self.crear_menu()
        self.crear_interfaz()
        self.configuracion = ConfiguracionView(self)
        self.configuracion_lotes = ConfiguracionLotesView(self)
        self.crear_barra_estado()

        # Formulario bloqueado al iniciar
        self.bloquear_formulario(True)

    # HELPERS DE UI
    @staticmethod
    def _etiqueta(texto):

        lbl = QLabel(texto)
        lbl.setObjectName("etiqueta")

        return lbl

    @staticmethod
    def _campo(texto="", centrado=False, solo_lectura=False):

        campo = QLineEdit(texto)

        if centrado:
            campo.setAlignment(Qt.AlignmentFlag.AlignCenter)

        if solo_lectura:
            campo.setReadOnly(True)

        return campo

    def _fila(self, *items):
        """
        items: widgets, o tuplas (widget, stretch).
        Devuelve un QWidget con los items en horizontal.
        """

        contenedor = QWidget()

        layout = QHBoxLayout(contenedor)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        for item in items:

            if isinstance(item, tuple):
                layout.addWidget(item[0], item[1])
            else:
                layout.addWidget(item)

        return contenedor

    @staticmethod
    def _boton(texto, alto=45, nombre=None):

        btn = QPushButton(texto)

        btn.setMinimumHeight(alto)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)

        if nombre:
            btn.setObjectName(nombre)

        return btn

    # MENÚ
    def crear_menu(self):

        barra = self.menuBar()

        # ---------------- ARCHIVO ----------------
        menu_archivo = barra.addMenu("&Archivo")

        self.act_salir = QAction("Salir", self)
        self.act_salir.setShortcut(QKeySequence("Ctrl+Q"))
        self.act_salir.triggered.connect(self.close)

        menu_archivo.addAction(self.act_salir)

        # ---------------- CONFIGURACIÓN ----------------
        menu_config = barra.addMenu("&Configuración")

        self.act_configuracion = QAction("Mostrar configuración avanzada", self)
        self.act_configuracion.setCheckable(True)
        self.act_configuracion.setShortcut(QKeySequence("Ctrl+,"))

        menu_config.addAction(self.act_configuracion)

        self.act_configuracion_lotes = QAction("Configuración de lotes", self)

        menu_config.addAction(self.act_configuracion_lotes)

        menu_config.addSeparator()

        self.act_actualizar_puertos = QAction("Actualizar puertos", self)
        self.act_actualizar_puertos.setShortcut(QKeySequence("F5"))

        menu_config.addAction(self.act_actualizar_puertos)

        # ---------------- AYUDA ----------------
        menu_ayuda = barra.addMenu("A&yuda")

        self.act_acerca = QAction("Acerca de", self)
        self.act_acerca.triggered.connect(self.mostrar_acerca)

        menu_ayuda.addAction(self.act_acerca)

        # ---------------- CONEXIONES ----------------
        self.act_configuracion.triggered.connect(self.mostrar_configuracion)

    # INTERFAZ PRINCIPAL
    def crear_interfaz(self):

        # El contenido va dentro de un scroll: si la pantalla es
        # pequeña (1366x768, 1024x768) nada queda cortado.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        central = QWidget()
        central.setObjectName("central")

        scroll.setWidget(central)
        self.setCentralWidget(scroll)

        principal = QVBoxLayout(central)
        principal.setContentsMargins(14, 10, 14, 10)
        principal.setSpacing(10)

        # BOTONES INICIAR / DETENER (conexión con la balanza)
        self.btn_iniciar = self._boton("▶  Iniciar", 38, "btn_iniciar")

        self.btn_detener = self._boton("■  Detener", 38, "btn_detener")
        self.btn_detener.setEnabled(False)

        # CABECERA
        cabecera = QHBoxLayout()
        cabecera.setSpacing(10)

        self.lbl_titulo = QLabel("⚖  FORMATO DE PESAJE AUTOMATIZADO")
        self.lbl_titulo.setStyleSheet("""
            QLabel {
                font-size: 22px;
                font-weight: bold;
                color: #111827;
                padding: 4px 0;
            }
            """)

        self.btn_pendientes = self._boton(
            "📋  PESAJES PENDIENTES", 40, "btn_pendientes"
        )

        self.btn_actualizar_maestros = self._boton(
            "🔄  Actualizar maestros", 40, "btn_actualizar_maestros"
        )

        cabecera.addWidget(self.lbl_titulo)
        cabecera.addStretch()
        cabecera.addWidget(self.btn_iniciar)
        cabecera.addWidget(self.btn_detener)
        cabecera.addSpacing(16)
        cabecera.addWidget(self.btn_pendientes)
        cabecera.addWidget(self.btn_actualizar_maestros)

        principal.addLayout(cabecera)

        # IDENTIFICACIÓN DE LA OPERACIÓN
        grupo_ident = QGroupBox("Identificación de la operación")

        lay_ident = QHBoxLayout(grupo_ident)
        lay_ident.setSpacing(10)

        self.txt_ticket = self._campo(centrado=True, solo_lectura=True)
        self.txt_lote = self._campo(centrado=True)

        # Combos con búsqueda (ver views/combo_busqueda.py)
        self.txt_placa = ComboBusqueda("Seleccionar placa")
        self.txt_carreta = ComboBusqueda("Seleccionar carreta")

        # Se conectan UNA sola vez, aquí
        self.txt_placa.currentIndexChanged.connect(self._seleccionar_vehiculo)
        self.txt_carreta.currentIndexChanged.connect(self._seleccionar_carreta)

        self.lbl_estado_operacion = QLabel()
        self.lbl_estado_operacion.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_estado_operacion.setMinimumHeight(34)

        lay_ident.addWidget(self._etiqueta("Ticket:"))
        lay_ident.addWidget(self.txt_ticket, 1)
        lay_ident.addWidget(self._etiqueta("Lote:"))
        lay_ident.addWidget(self.txt_lote, 1)
        lay_ident.addWidget(self._etiqueta("Placa:"))
        lay_ident.addWidget(self.txt_placa, 1)
        lay_ident.addWidget(self._etiqueta("Carreta:"))
        lay_ident.addWidget(self.txt_carreta, 1)
        lay_ident.addWidget(self._etiqueta("Estado:"))
        lay_ident.addWidget(self.lbl_estado_operacion, 1)

        principal.addWidget(grupo_ident)

        self.estado_operacion("proceso")

        # ÁREA CENTRAL: DATOS (izq.) + PESO (der.)
        operacion = QHBoxLayout()
        operacion.setSpacing(12)

        operacion.addWidget(self._crear_grupo_datos(), 3)
        operacion.addWidget(self._crear_grupo_peso(), 2)

        principal.addLayout(operacion, 1)

        # TABLA DE PESAJES
        principal.addWidget(self._crear_grupo_pesajes())

        # BOTONES OPERATIVOS
        acciones = QHBoxLayout()
        acciones.setSpacing(10)

        self.btn_nuevo = self._boton("＋  NUEVO")
        self.btn_guardar = self._boton("💾  GUARDAR", 45, "btn_guardar")
        self.btn_imprimir = self._boton("🖨  IMPRIMIR")
        self.btn_modificar = self._boton("✎  MODIFICAR")
        self.btn_salir = self._boton("🚪  SALIR")

        self.btn_salir.clicked.connect(self.close)

        acciones.addWidget(self.btn_nuevo)
        acciones.addWidget(self.btn_guardar, 1)
        acciones.addWidget(self.btn_imprimir)
        acciones.addWidget(self.btn_modificar)
        acciones.addStretch()
        acciones.addWidget(self.btn_salir)

        principal.addLayout(acciones)

        # SINCRONIZAR "LOTE ACTUAL"
        self.txt_lote.textChanged.connect(self._actualizar_lote_actual)

    # FORMULARIO DE OPERACIÓN
    def bloquear_formulario(self, bloquear=True):
        """
        Bloquea o desbloquea los campos de registro de la operación.
        """

        habilitado = not bloquear

        campos = [
            self.txt_lote,
            self.txt_placa,
            self.txt_carreta,
            self.txt_chofer,
            self.txt_brevete,
            self.txt_proveedor,
            self.txt_ruc_proveedor,
            self.txt_guia_proveedor,
            self.txt_transportista,
            self.txt_ruc_transportista,
            self.txt_guia_transportista,
            self.txt_concesion,
            self.txt_codigo,
            self.txt_procedencia,
            self.txt_producto,
            self.txt_observacion,
        ]

        for campo in campos:
            campo.setEnabled(habilitado)

        # El ticket se mantiene bloqueado.
        self.txt_ticket.setEnabled(False)

    def mostrar_ticket(self, ticket):
        self.txt_ticket.setText(str(ticket))

    def preparar_nuevo_registro(self, ticket, lote):
        """
        Prepara la interfaz para un nuevo pesaje.
        """

        # Solo campos de texto (QLineEdit).
        # Los combos NO van aquí: QComboBox.clear() borra sus items.
        campos = [
            self.txt_ticket,
            self.txt_lote,
            self.txt_chofer,
            self.txt_brevete,
            self.txt_proveedor,
            self.txt_ruc_proveedor,
            self.txt_guia_proveedor,
            self.txt_transportista,
            self.txt_ruc_transportista,
            self.txt_guia_transportista,
            self.txt_concesion,
            self.txt_codigo,
            self.txt_procedencia,
            self.txt_producto,
            self.txt_observacion,
        ]

        for campo in campos:
            campo.clear()

        # Combos: quita la selección y el texto, conserva los items
        self.txt_placa.limpiar()
        self.txt_carreta.limpiar()

        self.vehiculo_seleccionado = None
        self.carreta_seleccionada = None

        self.conductor_seleccionado = None
        self.proveedor_seleccionado = None
        self.transportista_seleccionado = None
        self.concesion_seleccionada = None

        self.limpiar_peso()
        self.tabla_pesajes.setRowCount(0)
        self.lbl_lote_actual.setText("Lote actual: —")

        self.mostrar_ticket(ticket)
        self.txt_lote.setText(lote or "")

        self.estado_operacion("proceso")
        self.bloquear_formulario(False)
        self.txt_lote.setFocus()

    # GRUPO: DATOS DEL VEHÍCULO Y CARGA
    def _crear_grupo_datos(self):

        grupo = QGroupBox("Datos del vehículo y carga")

        grid = QGridLayout(grupo)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(1, 1)

        # Campos
        self.txt_chofer = self._campo()
        self.txt_brevete = self._campo()

        self.txt_proveedor = self._campo()
        self.txt_ruc_proveedor = self._campo()
        self.txt_guia_proveedor = self._campo()

        self.txt_transportista = self._campo()
        self.txt_ruc_transportista = self._campo()
        self.txt_guia_transportista = self._campo()

        self.txt_concesion = self._campo()
        self.txt_codigo = self._campo()

        self.txt_procedencia = self._campo()
        self.txt_producto = self._campo()

        self.txt_observacion = self._campo()

        filas = [
            (
                "Chofer:",
                self._fila(
                    (self.txt_chofer, 3),
                    self._etiqueta("Brevete:"),
                    (self.txt_brevete, 2),
                ),
            ),
            (
                "Proveedor:",
                self._fila(
                    (self.txt_proveedor, 5),
                    self._etiqueta("RUC:"),
                    (self.txt_ruc_proveedor, 2),
                    self._etiqueta("Guía:"),
                    (self.txt_guia_proveedor, 2),
                ),
            ),
            (
                "Transportista:",
                self._fila(
                    (self.txt_transportista, 5),
                    self._etiqueta("RUC:"),
                    (self.txt_ruc_transportista, 2),
                    self._etiqueta("Guía:"),
                    (self.txt_guia_transportista, 2),
                ),
            ),
            (
                "Concesión:",
                self._fila(
                    (self.txt_concesion, 4),
                    self._etiqueta("Código:"),
                    (self.txt_codigo, 2),
                ),
            ),
            (
                "Procedencia:",
                self._fila(
                    (self.txt_procedencia, 3),
                    self._etiqueta("Producto:"),
                    (self.txt_producto, 3),
                ),
            ),
            (
                "Observación:",
                self.txt_observacion,
            ),
        ]

        for fila, (texto, widget) in enumerate(filas):

            etiqueta = self._etiqueta(texto)
            etiqueta.setMinimumWidth(100)

            grid.addWidget(etiqueta, fila, 0)
            grid.addWidget(widget, fila, 1)

        grid.setRowStretch(len(filas), 1)

        return grupo

    # GRUPO: PESO ACTUAL
    def _crear_grupo_peso(self):

        grupo = QGroupBox("Peso actual")

        layout = QVBoxLayout(grupo)
        layout.setSpacing(10)

        self.lbl_peso = QLabel("---")
        self.lbl_peso.setObjectName("lbl_peso")
        self.lbl_peso.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_peso.setMinimumHeight(150)

        lbl_info = QLabel("Lectura actual de la balanza")
        lbl_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_info.setStyleSheet("""
            QLabel {
                color: #6b7280;
                font-size: 13px;
                font-weight: normal;
            }
            """)

        self.btn_capturar = self._boton("⚖  CAPTURAR PESO", 58, "btn_capturar")

        self.lbl_lote_actual = QLabel("Lote actual: —")
        self.lbl_lote_actual.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_lote_actual.setStyleSheet("""
            QLabel {
                color: #374151;
                font-size: 14px;
                font-weight: bold;
                padding: 4px;
            }
            """)

        layout.addWidget(self.lbl_peso, 1)
        layout.addWidget(lbl_info)
        layout.addWidget(self.btn_capturar)
        layout.addWidget(self.lbl_lote_actual)

        return grupo

    # GRUPO: PESAJES DE LOS LOTES
    def _crear_grupo_pesajes(self):

        grupo = QGroupBox("Pesajes de los lotes")

        layout = QVBoxLayout(grupo)

        self.tabla_pesajes = QTableWidget()

        self.tabla_pesajes.setColumnCount(8)
        self.tabla_pesajes.setHorizontalHeaderLabels(
            [
                "LOTE",
                "SACOS",
                "1ª PESADA (FECHA / HORA)",
                "1ª PESADA (kg)",
                "2ª PESADA (FECHA / HORA)",
                "2ª PESADA (kg)",
                "PESO NETO (kg)",
                "ESTADO",
            ]
        )

        self.tabla_pesajes.verticalHeader().setVisible(False)
        self.tabla_pesajes.verticalHeader().setDefaultSectionSize(30)

        self.tabla_pesajes.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.tabla_pesajes.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.tabla_pesajes.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabla_pesajes.setAlternatingRowColors(True)
        self.tabla_pesajes.setMinimumHeight(140)
        self.tabla_pesajes.setMaximumHeight(190)

        header = self.tabla_pesajes.horizontalHeader()
        header.setStretchLastSection(False)

        for col in range(8):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)

        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)

        layout.addWidget(self.tabla_pesajes)

        return grupo

    # BARRA DE ESTADO
    def crear_barra_estado(self):

        barra = QStatusBar()
        barra.setSizeGripEnabled(False)

        self.setStatusBar(barra)

        self.lbl_estado_balanza = QLabel("⚪ Balanza desconectada")
        self.lbl_estado_display = QLabel("⚪ Display desconectado")
        self.lbl_estado = QLabel("Esperando...")

        for label in (
            self.lbl_estado_balanza,
            self.lbl_estado_display,
            self.lbl_estado,
        ):
            label.setStyleSheet("""
                QLabel {
                    font-weight: bold;
                    font-size: 13px;
                    padding: 2px 10px;
                }
                """)

        barra.addWidget(self.lbl_estado_balanza)
        barra.addWidget(self._separador())
        barra.addWidget(self.lbl_estado_display)
        barra.addPermanentWidget(self.lbl_estado)

    @staticmethod
    def _separador():

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)

        return sep

    # PESO
    def mostrar_peso(self, peso):

        self.lbl_peso.setText(f"{peso}<span style='font-size:28px;'> kg</span>")

    def limpiar_peso(self):

        self.lbl_peso.setText("---")

    # CONFIGURACIÓN AVANZADA: MOSTRAR / OCULTAR
    def mostrar_configuracion(self, visible):

        if visible:
            self.configuracion.show()
            self.configuracion.raise_()
            self.configuracion.activateWindow()
        else:
            self.configuracion.hide()

        self._sincronizar_accion_config(visible)

    def _sincronizar_accion_config(self, visible):

        self.act_configuracion.setChecked(visible)

        self.act_configuracion.setText(
            "Ocultar configuración avanzada"
            if visible
            else "Mostrar configuración avanzada"
        )

    # ACERCA DE
    def mostrar_acerca(self):

        QMessageBox.about(
            self,
            "Acerca de",
            f"{APP_NAME}\n\n" "Puente balanza → display.\n" "Minera MH S.A.C.",
        )

    # ESTADOS (barra inferior)
    def _estilo_estado(self, label, texto, color, size=13):

        label.setText(texto)

        label.setStyleSheet(f"""
            QLabel {{
                font-weight: bold;
                font-size: {size}px;
                padding: 2px 10px;
                color: {color};
            }}
            """)

    def estado_balanza(self, texto, color):

        self._estilo_estado(self.lbl_estado_balanza, texto, color)

    def estado_display(self, texto, color):

        self._estilo_estado(self.lbl_estado_display, texto, color)

    def estado_sistema(self, texto, color):

        self._estilo_estado(self.lbl_estado, texto, color, size=14)

    # ESTADO DE LA OPERACIÓN (ticket)
    def estado_operacion(self, tipo="proceso"):

        texto, fondo, color, borde = ESTADOS_OPERACION[tipo]

        self.lbl_estado_operacion.setText(texto)

        self.lbl_estado_operacion.setStyleSheet(f"""
            QLabel {{
                background-color: {fondo};
                color: {color};
                border: 1px solid {borde};
                border-radius: 6px;
                padding: 4px 10px;
                font-weight: bold;
            }}
            """)

    # CONTROLES
    def bloquear_configuracion(self, bloquear=True):

        self.configuracion.bloquear_configuracion(bloquear)
        self.act_actualizar_puertos.setEnabled(not bloquear)

    def log(self, texto):

        self.configuracion.log(texto)

    # TABLA DE PESAJES
    def cargar_pesajes(self, filas):
        """
        filas: lista de tuplas de 8 valores:
        (lote, sacos, fecha_hora_1, peso_1, fecha_hora_2, peso_2, neto, estado)
        """

        self.tabla_pesajes.setRowCount(len(filas))

        for r, valores in enumerate(filas):

            for c, valor in enumerate(valores):

                item = QTableWidgetItem(str(valor))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

                if c == 7:
                    color = "#15803d" if str(valor) == "COMPLETO" else "#b45309"
                    item.setForeground(QColor(color))

                    fuente = item.font()
                    fuente.setBold(True)
                    item.setFont(fuente)

                self.tabla_pesajes.setItem(r, c, item)

    # MAESTROS
    def cargar_maestros(
        self, vehiculos, carretas, conductores, proveedores, transportistas, concesiones
    ):
        """
        Recibe los datos maestros desde el Controller.
        """

        self.maestros = {
            "vehiculos": vehiculos,
            "carretas": carretas,
            "conductores": conductores,
            "proveedores": proveedores,
            "transportistas": transportistas,
            "concesiones": concesiones,
        }

        # Combos de vehículo y carreta
        indice = self.txt_placa.cargar(vehiculos)
        self._seleccionar_vehiculo(indice)

        indice = self.txt_carreta.cargar(carretas)
        self._seleccionar_carreta(indice)

        # Autocompletados
        self._configurar_autocompletado_proveedor()
        self._configurar_autocompletado_chofer()
        self._configurar_autocompletado_transportista()
        self._configurar_autocompletado_concesion()

    def _configurar_autocompletado_proveedor(self):
        """
        Configura el autocompletado de proveedor y RUC.

        El dato principal aparece arriba y el dato complementario
        aparece debajo.
        """

        proveedores = self.maestros.get("proveedores", [])

        if not proveedores:
            return

        # AUTOCOMPLETADO: PROVEEDOR
        # Principal: nombre
        # Complementario: RUC
        opciones_proveedor = [
            f"{proveedor[1]}\n{proveedor[2]}" for proveedor in proveedores
        ]

        modelo_proveedor = QStringListModel(opciones_proveedor, self)
        self.completer_proveedor = QCompleter(modelo_proveedor, self)
        self.completer_proveedor.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.completer_proveedor.setFilterMode(Qt.MatchFlag.MatchContains)
        self.completer_proveedor.setCompletionMode(
            QCompleter.CompletionMode.PopupCompletion
        )
        self.txt_proveedor.setCompleter(self.completer_proveedor)
        self.completer_proveedor.activated[str].connect(
            lambda texto: QTimer.singleShot(
                0, lambda: self._seleccionar_proveedor(texto)
            )
        )

        # AUTOCOMPLETADO: RUC
        # Principal: RUC
        # Complementario: nombre
        opciones_ruc = [f"{proveedor[2]}\n{proveedor[1]}" for proveedor in proveedores]

        modelo_ruc = QStringListModel(opciones_ruc, self)
        self.completer_ruc_proveedor = QCompleter(modelo_ruc, self)
        self.completer_ruc_proveedor.setCaseSensitivity(
            Qt.CaseSensitivity.CaseInsensitive
        )
        self.completer_ruc_proveedor.setFilterMode(Qt.MatchFlag.MatchContains)
        self.completer_ruc_proveedor.setCompletionMode(
            QCompleter.CompletionMode.PopupCompletion
        )
        self.txt_ruc_proveedor.setCompleter(self.completer_ruc_proveedor)
        self.completer_ruc_proveedor.activated[str].connect(
            lambda texto: QTimer.singleShot(
                0, lambda: self._seleccionar_proveedor(texto)
            )
        )

    def _configurar_autocompletado_chofer(self):
        """
        Configura el autocompletado de chofer y brevete.

        El dato principal aparece arriba y el dato complementario
        aparece debajo.
        """

        conductores = self.maestros.get("conductores", [])

        if not conductores:
            return

        # AUTOCOMPLETADO: CHOFER
        # Principal: nombre
        # Complementario: brevete
        opciones_chofer = [
            f"{conductor[1]}\n{conductor[2]}" for conductor in conductores
        ]

        modelo_chofer = QStringListModel(opciones_chofer, self)
        self.completer_chofer = QCompleter(modelo_chofer, self)
        self.completer_chofer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.completer_chofer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.completer_chofer.setCompletionMode(
            QCompleter.CompletionMode.PopupCompletion
        )
        self.txt_chofer.setCompleter(self.completer_chofer)

        self.completer_chofer.activated[str].connect(
            lambda texto: QTimer.singleShot(0, lambda: self._seleccionar_chofer(texto))
        )

        # AUTOCOMPLETADO: BREVETE
        # Principal: brevete
        # Complementario: nombre
        opciones_brevete = [
            f"{conductor[2]}\n{conductor[1]}" for conductor in conductores
        ]

        modelo_brevete = QStringListModel(opciones_brevete, self)
        self.completer_brevete = QCompleter(modelo_brevete, self)
        self.completer_brevete.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.completer_brevete.setFilterMode(Qt.MatchFlag.MatchContains)
        self.completer_brevete.setCompletionMode(
            QCompleter.CompletionMode.PopupCompletion
        )
        self.txt_brevete.setCompleter(self.completer_brevete)

        self.completer_brevete.activated[str].connect(
            lambda texto: QTimer.singleShot(0, lambda: self._seleccionar_chofer(texto))
        )

    def _configurar_autocompletado_transportista(self):
        """
        Configura el autocompletado de transportista y RUC.

        El dato principal aparece arriba y el dato complementario
        aparece debajo.
        """

        transportistas = self.maestros.get("transportistas", [])

        if not transportistas:
            return

        # AUTOCOMPLETADO: TRANSPORTISTA
        # Principal: nombre
        # Complementario: RUC
        opciones_transportista = [
            f"{transportista[1]}\n{transportista[2]}"
            for transportista in transportistas
        ]

        modelo_transportista = QStringListModel(opciones_transportista, self)
        self.completer_transportista = QCompleter(modelo_transportista, self)
        self.completer_transportista.setCaseSensitivity(
            Qt.CaseSensitivity.CaseInsensitive
        )
        self.completer_transportista.setFilterMode(Qt.MatchFlag.MatchContains)
        self.completer_transportista.setCompletionMode(
            QCompleter.CompletionMode.PopupCompletion
        )
        self.txt_transportista.setCompleter(self.completer_transportista)

        self.completer_transportista.activated[str].connect(
            lambda texto: QTimer.singleShot(
                0, lambda: self._seleccionar_transportista(texto)
            )
        )

        # AUTOCOMPLETADO: RUC
        # Principal: RUC
        # Complementario: nombre
        opciones_ruc = [
            f"{transportista[2]}\n{transportista[1]}"
            for transportista in transportistas
        ]

        modelo_ruc = QStringListModel(opciones_ruc, self)
        self.completer_ruc_transportista = QCompleter(modelo_ruc, self)
        self.completer_ruc_transportista.setCaseSensitivity(
            Qt.CaseSensitivity.CaseInsensitive
        )
        self.completer_ruc_transportista.setFilterMode(Qt.MatchFlag.MatchContains)
        self.completer_ruc_transportista.setCompletionMode(
            QCompleter.CompletionMode.PopupCompletion
        )
        self.txt_ruc_transportista.setCompleter(self.completer_ruc_transportista)

        self.completer_ruc_transportista.activated[str].connect(
            lambda texto: QTimer.singleShot(
                0, lambda: self._seleccionar_transportista(texto)
            )
        )

    def _configurar_autocompletado_concesion(self):
        """
        Configura el autocompletado de concesión y código.

        El dato principal aparece arriba y el dato complementario
        aparece debajo.
        """

        concesiones = self.maestros.get("concesiones", [])

        if not concesiones:
            return

        # AUTOCOMPLETADO: CONCESIÓN
        # Principal: nombre
        # Complementario: código
        opciones_concesion = [
            f"{concesion[1]}\n{concesion[2]}" for concesion in concesiones
        ]

        modelo_concesion = QStringListModel(opciones_concesion, self)
        self.completer_concesion = QCompleter(modelo_concesion, self)
        self.completer_concesion.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.completer_concesion.setFilterMode(Qt.MatchFlag.MatchContains)
        self.completer_concesion.setCompletionMode(
            QCompleter.CompletionMode.PopupCompletion
        )
        self.txt_concesion.setCompleter(self.completer_concesion)

        self.completer_concesion.activated[str].connect(
            lambda texto: QTimer.singleShot(
                0, lambda: self._seleccionar_concesion(texto)
            )
        )

        # AUTOCOMPLETADO: CÓDIGO
        # Principal: código
        # Complementario: nombre
        opciones_codigo = [
            f"{concesion[2]}\n{concesion[1]}" for concesion in concesiones
        ]

        modelo_codigo = QStringListModel(opciones_codigo, self)
        self.completer_codigo = QCompleter(modelo_codigo, self)
        self.completer_codigo.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.completer_codigo.setFilterMode(Qt.MatchFlag.MatchContains)
        self.completer_codigo.setCompletionMode(
            QCompleter.CompletionMode.PopupCompletion
        )
        self.txt_codigo.setCompleter(self.completer_codigo)

        self.completer_codigo.activated[str].connect(
            lambda texto: QTimer.singleShot(
                0, lambda: self._seleccionar_concesion(texto)
            )
        )

    # SELECCIÓN: VEHÍCULO Y CARRETA
    def _seleccionar_vehiculo(self, indice):
        """
        Guarda internamente el vehículo seleccionado.
        """

        if indice < 0:
            self.vehiculo_seleccionado = None
            return

        self.vehiculo_seleccionado = {
            "id_vehiculo": self.txt_placa.itemData(indice),
            "placa": self.txt_placa.itemText(indice),
        }

    def _seleccionar_carreta(self, indice):
        """
        Guarda internamente la carreta seleccionada.
        """

        if indice < 0:
            self.carreta_seleccionada = None
            return

        self.carreta_seleccionada = {
            "id_carreta": self.txt_carreta.itemData(indice),
            "placa": self.txt_carreta.itemText(indice),
        }

    # SELECCIÓN: PROVEEDOR / CHOFER / TRANSPORTISTA / CONCESIÓN
    def _seleccionar_proveedor(self, texto):

        proveedores = self.maestros.get("proveedores", [])

        # Separar las dos líneas de la opción seleccionada
        partes = texto.splitlines()

        if len(partes) < 2:
            return

        dato_principal = partes[0].strip()
        dato_complementario = partes[1].strip()

        for proveedor in proveedores:
            id_proveedor = proveedor[0]
            nombre = proveedor[1]
            ruc = proveedor[2]

            # Selección desde PROVEEDOR: principal = nombre, complementario = RUC
            # Selección desde RUC: principal = RUC, complementario = nombre
            if (dato_principal == nombre and dato_complementario == ruc) or (
                dato_principal == ruc and dato_complementario == nombre
            ):
                self.proveedor_seleccionado = {
                    "id_proveedor": id_proveedor,
                    "nombre": nombre,
                    "ruc": ruc,
                }

                self.txt_proveedor.setText(nombre)
                self.txt_ruc_proveedor.setText(ruc)

                return

    def _seleccionar_chofer(self, texto):
        """
        Selecciona un chofer desde el autocompletado
        y sincroniza nombre, brevete e ID interno.
        """

        conductores = self.maestros.get("conductores", [])

        partes = texto.splitlines()

        if len(partes) < 2:
            return

        dato_principal = partes[0].strip()
        dato_complementario = partes[1].strip()

        for conductor in conductores:

            id_conductor = conductor[0]
            nombre = conductor[1]
            brevete = conductor[2]

            # Desde CHOFER: principal = nombre, complementario = brevete
            # Desde BREVETE: principal = brevete, complementario = nombre
            if (dato_principal == nombre and dato_complementario == brevete) or (
                dato_principal == brevete and dato_complementario == nombre
            ):
                self.conductor_seleccionado = {
                    "id_conductor": id_conductor,
                    "nombre": nombre,
                    "brevete": brevete,
                }

                self.txt_chofer.setText(nombre)
                self.txt_brevete.setText(brevete)

                return

    def _seleccionar_transportista(self, texto):
        """
        Selecciona un transportista desde el autocompletado
        y sincroniza nombre, RUC e ID interno.
        """

        transportistas = self.maestros.get("transportistas", [])

        partes = texto.splitlines()

        if len(partes) < 2:
            return

        dato_principal = partes[0].strip()
        dato_complementario = partes[1].strip()

        for transportista in transportistas:

            id_transportista = transportista[0]
            nombre = transportista[1]
            ruc = transportista[2]

            # Desde TRANSPORTISTA: principal = nombre, complementario = RUC
            # Desde RUC: principal = RUC, complementario = nombre
            if (dato_principal == nombre and dato_complementario == ruc) or (
                dato_principal == ruc and dato_complementario == nombre
            ):
                self.transportista_seleccionado = {
                    "id_transportista": id_transportista,
                    "nombre": nombre,
                    "ruc": ruc,
                }

                self.txt_transportista.setText(nombre)
                self.txt_ruc_transportista.setText(ruc)

                return

    def _seleccionar_concesion(self, texto):
        """
        Selecciona una concesión desde el autocompletado
        y sincroniza nombre, código e ID interno.
        """

        concesiones = self.maestros.get("concesiones", [])

        partes = texto.splitlines()

        if len(partes) < 2:
            return

        dato_principal = partes[0].strip()
        dato_complementario = partes[1].strip()

        for concesion in concesiones:

            id_concesion = concesion[0]
            nombre = concesion[1]
            codigo = concesion[2]

            # Desde CONCESIÓN: principal = nombre, complementario = código
            # Desde CÓDIGO: principal = código, complementario = nombre
            if (dato_principal == nombre and dato_complementario == codigo) or (
                dato_principal == codigo and dato_complementario == nombre
            ):
                self.concesion_seleccionada = {
                    "id_concesion": id_concesion,
                    "nombre": nombre,
                    "codigo": codigo,
                }

                self.txt_concesion.setText(nombre)
                self.txt_codigo.setText(codigo)

                return

    # DATOS DE LA OPERACIÓN
    def obtener_datos_operacion(self):

        return {
            "ticket": self.txt_ticket.text().strip(),
            "lote": self.txt_lote.text().strip(),
            "placa": self.txt_placa.currentText().strip(),
            "carreta": self.txt_carreta.currentText().strip(),
            # El ID se calcula con el texto actual del combo:
            # None si la placa se escribió a mano y no está en la lista.
            "id_vehiculo": self.txt_placa.id_actual(),
            "id_carreta": self.txt_carreta.id_actual(),
            "chofer": self.txt_chofer.text().strip(),
            "brevete": self.txt_brevete.text().strip(),
            "proveedor": self.txt_proveedor.text().strip(),
            "ruc_proveedor": self.txt_ruc_proveedor.text().strip(),
            "guia_proveedor": self.txt_guia_proveedor.text().strip(),
            "transportista": self.txt_transportista.text().strip(),
            "ruc_transportista": self.txt_ruc_transportista.text().strip(),
            "guia_transportista": self.txt_guia_transportista.text().strip(),
            "concesion": self.txt_concesion.text().strip(),
            "codigo": self.txt_codigo.text().strip(),
            "procedencia": self.txt_procedencia.text().strip(),
            "producto": self.txt_producto.text().strip(),
            "observacion": self.txt_observacion.text().strip(),
        }

    def _actualizar_lote_actual(self, texto):

        self.lbl_lote_actual.setText(f"Lote actual: {texto.strip() or '—'}")

    # CERRAR VENTANA
    def closeEvent(self, event):

        # Si el diálogo de configuración queda abierto, la app
        # no terminaría al cerrar la ventana principal.
        self.configuracion.close()

        self.cerrando.emit()

        event.accept()
