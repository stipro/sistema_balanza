from PyQt6.QtCore import Qt, QEvent
from PyQt6.QtWidgets import QComboBox, QCompleter


class ComboBusqueda(QComboBox):
    """
    Combo editable con búsqueda:

    - Al hacer click en el campo se muestra la lista completa.
    - Al escribir se filtran las coincidencias parciales.
    - Cada item guarda un ID interno mediante userData.
    - Puede conservar la selección al actualizar maestros.
    """

    def __init__(self, placeholder="", parent=None):

        super().__init__(parent)

        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.setDuplicatesEnabled(False)
        self.setMaxVisibleItems(10)
        self.setPlaceholderText(placeholder)

        self.lineEdit().setAlignment(Qt.AlignmentFlag.AlignCenter)

        # COMPLETER
        completer = QCompleter(self.model(), self)

        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

        completer.setFilterMode(Qt.MatchFlag.MatchContains)

        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)

        completer.setMaxVisibleItems(10)

        self.setCompleter(completer)

        # Detectar clicks sobre el campo de texto
        self.lineEdit().installEventFilter(self)

    def setEnabled(self, habilitado):
        """
        Habilita o deshabilita completamente el combo
        y su campo interno.
        """

        super().setEnabled(habilitado)

        if self.lineEdit():
            self.lineEdit().setEnabled(habilitado)

        # Si se deshabilita, cerrar cualquier popup abierto.
        if not habilitado:
            if self.completer():
                self.completer().popup().hide()

            self.hidePopup()

    def showPopup(self):
        """
        Muestra la lista solamente si el combo está habilitado.
        """

        if not self.isEnabled():
            return

        super().showPopup()

    def eventFilter(self, obj, event):
        """
        Al hacer click en el campo de texto muestra
        la lista completa, pero solamente si el combo
        está habilitado.
        """

        if not self.isEnabled():
            return super().eventFilter(obj, event)

        if obj is self.lineEdit() and event.type() == QEvent.Type.MouseButtonPress:
            self.completer().setCompletionPrefix("")
            self.completer().complete()

        return super().eventFilter(obj, event)

    def cargar(self, items):
        """
        items: lista de tuplas (id, texto, ...).

        Recarga los items conservando la selección anterior
        si existe.
        """

        id_anterior = self.id_actual()

        self.blockSignals(True)

        self.clear()

        for item in items:
            self.addItem(str(item[1]), item[0])

        indice = self.findData(id_anterior) if id_anterior is not None else -1

        self.setCurrentIndex(indice)

        if indice < 0:
            self.clearEditText()

        self.blockSignals(False)

        return indice

    def id_actual(self):
        """
        Devuelve el ID del item cuyo texto coincide
        con lo escrito.

        Si no existe coincidencia devuelve None.
        """

        texto = self.currentText().strip()

        if not texto:
            return None

        indice = self.findText(texto, Qt.MatchFlag.MatchFixedString)

        return self.itemData(indice) if indice >= 0 else None

    def limpiar(self):
        """
        Quita la selección y el texto,
        sin borrar los items.
        """

        self.setCurrentIndex(-1)
        self.clearEditText()
