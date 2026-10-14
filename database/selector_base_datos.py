"""Selector seguro de bases de datos SQLite para SistemaBalanza.

La ruta seleccionada NO se guarda aquí. El llamador la persiste únicamente
cuando la base supera las validaciones y, si es nueva, se inicializa bien.
"""
import json
import sqlite3
from pathlib import Path

from PyQt6.QtCore import QStandardPaths, Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFileDialog, QMessageBox, QLineEdit,
)

from database.conexion import DB_PATH


def directorio_configuracion():
    base = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppConfigLocation
    )
    if not base:
        base = str(Path.home() / ".config" / "SistemaBalanza")
    ruta = Path(base)
    ruta.mkdir(parents=True, exist_ok=True)
    return ruta


def archivo_configuracion():
    return directorio_configuracion() / "database.json"


def cargar_ruta_guardada():
    try:
        datos = json.loads(archivo_configuracion().read_text(encoding="utf-8"))
        ruta = datos.get("database_path")
        if ruta and Path(ruta).is_file():
            return Path(ruta).expanduser().resolve()
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return None


def guardar_ruta(ruta):
    """Persiste la ruta de forma atómica. Llamar solo tras validar la base."""
    destino = archivo_configuracion()
    temporal = destino.with_suffix(".tmp")
    temporal.write_text(
        json.dumps({"database_path": str(Path(ruta).expanduser().resolve())},
                   indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    temporal.replace(destino)


class SelectorBaseDatosDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configuración de base de datos")
        self.setMinimumWidth(640)
        self.ruta_elegida = None
        self.es_nueva = False

        guardada = cargar_ruta_guardada()
        inicial = guardada or (DB_PATH.resolve() if DB_PATH.exists() else None)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Seleccione la base SQLite con la que trabajará esta instalación.\n"
            "La ruta solo se guardará cuando la base haya sido validada correctamente."
        ))

        fila = QHBoxLayout()
        self.txt_ruta = QLineEdit(str(inicial) if inicial else "")
        self.txt_ruta.setReadOnly(True)
        self.txt_ruta.setPlaceholderText("Seleccione un archivo .db o .sqlite")
        fila.addWidget(self.txt_ruta, 1)
        btn_buscar = QPushButton("Seleccionar existente...")
        btn_buscar.clicked.connect(self.seleccionar_existente)
        fila.addWidget(btn_buscar)
        layout.addLayout(fila)

        botones = QHBoxLayout()
        self.btn_crear = QPushButton("Crear base nueva...")
        self.btn_crear.clicked.connect(self.crear_nueva)
        botones.addWidget(self.btn_crear)
        botones.addStretch()
        btn_cancelar = QPushButton("Salir")
        btn_cancelar.clicked.connect(self.reject)
        botones.addWidget(btn_cancelar)
        self.btn_usar = QPushButton("Usar esta base")
        self.btn_usar.setDefault(True)
        self.btn_usar.clicked.connect(self.aceptar_ruta)
        botones.addWidget(self.btn_usar)
        layout.addLayout(botones)

    def seleccionar_existente(self):
        ruta, _ = QFileDialog.getOpenFileName(
            self, "Seleccionar base SQLite", str(Path.home()),
            "Bases SQLite (*.db *.sqlite *.sqlite3);;Todos los archivos (*)",
        )
        if ruta:
            self.es_nueva = False
            self.txt_ruta.setText(str(Path(ruta).expanduser().resolve()))

    def crear_nueva(self):
        ruta, _ = QFileDialog.getSaveFileName(
            self, "Crear nueva base SQLite", str(Path.home() / "balanza.db"),
            "Base SQLite (*.db)",
        )
        if not ruta:
            return
        ruta = Path(ruta).expanduser()
        if ruta.suffix.lower() not in (".db", ".sqlite", ".sqlite3"):
            ruta = ruta.with_suffix(".db")
        if ruta.exists():
            QMessageBox.warning(
                self, "El archivo ya existe",
                "Ese archivo ya existe. No se sobrescribirá ni se vaciará.\n\n"
                "Seleccione la base existente o elija otro nombre para crear una nueva.",
            )
            return
        try:
            ruta.parent.mkdir(parents=True, exist_ok=True)
            # Exclusivo: evita sobrescribir un archivo creado entre la comprobación y aquí.
            with ruta.open("xb"):
                pass
            cx = sqlite3.connect(str(ruta))
            try:
                cx.execute("PRAGMA user_version = 0")
            finally:
                cx.close()
            self.es_nueva = True
            self.txt_ruta.setText(str(ruta.resolve()))
        except FileExistsError:
            QMessageBox.warning(self, "El archivo ya existe", "No se sobrescribió el archivo existente.")
        except (OSError, sqlite3.DatabaseError) as exc:
            QMessageBox.critical(self, "No se pudo crear la base", str(exc))

    def aceptar_ruta(self):
        texto = self.txt_ruta.text().strip()
        if not texto:
            QMessageBox.information(self, "Seleccione una base", "Seleccione o cree una base SQLite.")
            return
        ruta = Path(texto).expanduser().resolve()
        if not ruta.exists() or not ruta.is_file():
            QMessageBox.warning(self, "Archivo no encontrado", "La base seleccionada no existe.")
            return
        try:
            with ruta.open("rb") as archivo:
                cabecera = archivo.read(16)
            if cabecera != b"SQLite format 3\x00":
                QMessageBox.warning(self, "Archivo no válido", "El archivo seleccionado no parece ser una base SQLite.")
                return
            # Comprueba integridad sin guardar aún la ruta de configuración.
            cx = sqlite3.connect(str(ruta), timeout=5)
            try:
                resultado = cx.execute("PRAGMA quick_check").fetchone()
            finally:
                cx.close()
            if not resultado or resultado[0] != "ok":
                QMessageBox.warning(self, "Base con errores", "SQLite detectó un problema en el archivo.")
                return
        except (OSError, sqlite3.DatabaseError) as exc:
            QMessageBox.critical(self, "No se pudo validar", str(exc))
            return
        self.ruta_elegida = ruta
        self.accept()


def seleccionar_base_datos(forzar_seleccion=False, incluir_detalle=False):
    """Devuelve la ruta; con incluir_detalle=True devuelve (ruta, es_nueva).

    Si hay una ruta guardada existente, se reutiliza sin mostrar el selector.
    """
    if not forzar_seleccion:
        guardada = cargar_ruta_guardada()
        if guardada is not None:
            return (guardada, False) if incluir_detalle else guardada

    dialogo = SelectorBaseDatosDialog()
    dialogo.setWindowFlag(Qt.WindowType.Window, True)
    dialogo.setWindowModality(Qt.WindowModality.ApplicationModal)
    if dialogo.exec() == QDialog.DialogCode.Accepted:
        resultado = (dialogo.ruta_elegida, dialogo.es_nueva)
        return resultado if incluir_detalle else resultado[0]
    return (None, False) if incluir_detalle else None
