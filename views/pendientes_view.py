from PyQt6.QtWidgets import (
    QDialog,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QAbstractItemView,
    QHeaderView,
)
from PyQt6.QtCore import Qt


class PendientesView(QDialog):
    """Lista los ingresos EN_PROCESO para continuarlos."""

    def __init__(self, pendientes, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Pesajes pendientes")
        self.resize(720, 380)
        self.id_seleccionado = None

        self.tabla = QTableWidget(len(pendientes), 6)
        self.tabla.setHorizontalHeaderLabels(
            ["TICKET", "PLACA", "CHOFER", "LOTES OK", "CAPTURAS", "INICIADO"]
        )
        self.tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabla.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )

        for r, p in enumerate(pendientes):
            valores = (
                p["ticket"],
                p["placa"] or "—",
                p["chofer"] or "—",
                f"{p['lotes_completos']}/{p['total_lotes']}",
                p["capturas"],
                p["created_at"].replace("T", " "),
            )
            for c, v in enumerate(valores):
                item = QTableWidgetItem(str(v))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if c == 0:
                    item.setData(Qt.ItemDataRole.UserRole, p["id_pesaje"])
                self.tabla.setItem(r, c, item)

        self.btn_continuar = QPushButton("▶  Continuar seleccionado")
        self.btn_cancelar = QPushButton("Cerrar")
        self.btn_continuar.setEnabled(False)

        botones = QHBoxLayout()
        botones.addStretch()
        botones.addWidget(self.btn_cancelar)
        botones.addWidget(self.btn_continuar)

        layout = QVBoxLayout(self)
        layout.addWidget(self.tabla)
        layout.addLayout(botones)

        self.tabla.itemSelectionChanged.connect(self._seleccion)
        self.btn_continuar.clicked.connect(self.accept)
        self.btn_cancelar.clicked.connect(self.reject)

    def _seleccion(self):
        filas = self.tabla.selectedItems()
        self.btn_continuar.setEnabled(bool(filas))
        if filas:
            self.id_seleccionado = filas[0].data(Qt.ItemDataRole.UserRole)
