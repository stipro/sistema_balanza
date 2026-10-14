from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QMessageBox,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)


class PesajesView(QDialog):
    """Listado de ingresos de balanza de todos los estados."""

    def __init__(self, ingresos, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Pesajes - Todos los ingresos")
        self.resize(1050, 480)
        self.id_seleccionado = None
        self.estado_seleccionado = None

        self.tabla = QTableWidget(len(ingresos), 8)
        self.tabla.setHorizontalHeaderLabels([
            "TICKET", "PLACA", "CHOFER", "LOTES COMPLETOS", "LOTES", "CAPTURAS", "FECHA", "ESTADO"
        ])
        self.tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabla.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tabla.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

        for r, ingreso in enumerate(ingresos):
            fecha = str(ingreso.get("created_at") or "—").replace("T", " ")
            valores = (
                ingreso.get("ticket", "—"), ingreso.get("placa") or "—",
                ingreso.get("chofer") or "—",
                f"{ingreso.get('lotes_completos', 0)}/{ingreso.get('total_lotes', 0)}",
                ingreso.get("total_lotes", 0), ingreso.get("capturas", 0),
                fecha, ingreso.get("estado", "—"),
            )
            for c, valor in enumerate(valores):
                item = QTableWidgetItem(str(valor))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if c == 0:
                    item.setData(Qt.ItemDataRole.UserRole, ingreso["id_pesaje"])
                    item.setData(Qt.ItemDataRole.UserRole + 1, ingreso.get("estado"))
                if c == 7:
                    item.setForeground(Qt.GlobalColor.darkGreen if ingreso.get("estado") == "CONFIRMADO" else Qt.GlobalColor.darkRed if ingreso.get("estado") == "ANULADO" else Qt.GlobalColor.darkBlue)
                self.tabla.setItem(r, c, item)

        self.btn_ver = QPushButton("VER DETALLE")
        self.btn_cerrar = QPushButton("CERRAR")
        self.btn_ver.setEnabled(False)
        botones = QHBoxLayout()
        botones.addStretch()
        botones.addWidget(self.btn_cerrar)
        botones.addWidget(self.btn_ver)
        layout = QVBoxLayout(self)
        layout.addWidget(self.tabla)
        layout.addLayout(botones)
        self.tabla.itemSelectionChanged.connect(self._seleccion)
        self.tabla.itemDoubleClicked.connect(lambda *_: self.accept())
        self.btn_ver.clicked.connect(self.accept)
        self.btn_cerrar.clicked.connect(self.reject)

    def _seleccion(self):
        items = self.tabla.selectedItems()
        self.btn_ver.setEnabled(bool(items))
        if items:
            fila = self.tabla.currentRow()
            item = self.tabla.item(fila, 0)
            self.id_seleccionado = item.data(Qt.ItemDataRole.UserRole)
            self.estado_seleccionado = item.data(Qt.ItemDataRole.UserRole + 1)
