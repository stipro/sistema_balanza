"""Punto de entrada de SistemaBalanza con selección segura de SQLite."""
import sys
import sqlite3
from pathlib import Path

from PyQt6.QtWidgets import QApplication, QMessageBox

from database.conexion import usar_base_datos, ruta_base_datos
from database.selector_base_datos import (
    seleccionar_base_datos, cargar_ruta_guardada, guardar_ruta,
)
from database.esquema import inicializar_base_datos, VERSION_ESQUEMA
from views.balanza_view import BalanzaView
from controllers.balanza_controller import BalanzaController

TABLAS_REQUERIDAS = {"pesajes", "pesajes_lotes", "pesajes_registros"}


def validar_archivo_sqlite(ruta):
    """Valida formato e integridad sin modificar datos de usuario."""
    ruta = Path(ruta).expanduser().resolve()
    if not ruta.is_file():
        raise ValueError(f"No existe el archivo SQLite seleccionado:\n{ruta}")
    try:
        with ruta.open("rb") as archivo:
            cabecera = archivo.read(16)
        if cabecera != b"SQLite format 3\x00":
            raise ValueError("El archivo seleccionado no tiene una cabecera SQLite válida.")
        cx = sqlite3.connect(str(ruta), timeout=5)
        try:
            resultado = cx.execute("PRAGMA quick_check").fetchone()
            if not resultado or resultado[0] != "ok":
                raise ValueError("SQLite reportó que el archivo necesita revisión.")
        finally:
            cx.close()
    except sqlite3.DatabaseError as exc:
        raise ValueError(f"No se pudo validar la base SQLite:\n{exc}") from exc
    return ruta


def inspeccionar_esquema(ruta):
    """Devuelve tablas y versión sin ejecutar DDL ni modificar la base."""
    cx = sqlite3.connect(str(ruta), timeout=5)
    try:
        tablas = {
            fila[0] for fila in cx.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        version = cx.execute("PRAGMA user_version").fetchone()[0]
        return tablas, version
    finally:
        cx.close()


def validar_esquema_existente(ruta):
    """Acepta solo una BD del esquema esperado; nunca la migra automáticamente."""
    tablas, version = inspeccionar_esquema(ruta)
    faltantes = TABLAS_REQUERIDAS - tablas
    if faltantes:
        nombres = ", ".join(sorted(faltantes))
        raise ValueError(
            "La base seleccionada no contiene todas las tablas principales.\n"
            f"Faltan: {nombres}\n\n"
            "Si desea una base vacía, use 'Crear base nueva...' en el selector. "
            "No se modificó la base seleccionada."
        )
    if version != VERSION_ESQUEMA:
        raise ValueError(
            f"La base tiene la versión de esquema {version}, pero esta aplicación "
            f"requiere la versión {VERSION_ESQUEMA}.\n\n"
            "Por seguridad no se ejecutó ninguna migración automática ni se borraron datos."
        )


def preparar_base(ruta, es_nueva=False):
    """Valida una base existente o inicializa una base recién creada."""
    ruta = validar_archivo_sqlite(ruta)
    if es_nueva:
        usar_base_datos(ruta)
        inicializar_base_datos()
        validar_archivo_sqlite(ruta)
        validar_esquema_existente(ruta)
    else:
        validar_esquema_existente(ruta)
    return ruta


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("SistemaBalanza")
    app.setOrganizationName("MineraMH")

    ruta_seleccionada, es_nueva = seleccionar_base_datos(incluir_detalle=True)
    if ruta_seleccionada is None:
        return 0

    ruta_anterior = Path(ruta_base_datos()).resolve()
    try:
        ruta = preparar_base(ruta_seleccionada, es_nueva=es_nueva)
        # La configuración persistente se actualiza únicamente tras validar todo.
        guardar_ruta(ruta)
        usar_base_datos(ruta)
    except Exception as exc:
        usar_base_datos(ruta_anterior)
        QMessageBox.critical(
            None, "Error de base de datos",
            "No se pudo activar la base seleccionada.\n\n"
            f"Detalle: {exc}\n\n"
            "La ruta anterior guardada no se ha reemplazado y no se eliminó ningún archivo.",
        )
        return 1

    view = BalanzaView()
    controller = BalanzaController(view)

    def cambiar_base_datos():
        if getattr(controller, "ingreso_actual", None) is not None:
            QMessageBox.warning(
                view, "Operación en curso",
                "No se puede cambiar la base mientras haya un ingreso abierto.\n"
                "Guarde o cancele la operación y vuelva a intentarlo.",
            )
            return

        activa = Path(ruta_base_datos()).resolve()
        nueva, es_nueva_local = seleccionar_base_datos(
            forzar_seleccion=True, incluir_detalle=True
        )
        if nueva is None:
            return
        nueva = Path(nueva).resolve()
        if nueva == activa:
            QMessageBox.information(view, "Base de datos", "Esa base ya está seleccionada.")
            return

        try:
            if es_nueva_local:
                # Inicializa temporalmente la nueva BD, y luego restaura la ruta activa.
                usar_base_datos(nueva)
                try:
                    inicializar_base_datos()
                    validar_archivo_sqlite(nueva)
                    validar_esquema_existente(nueva)
                finally:
                    usar_base_datos(activa)
            else:
                validar_archivo_sqlite(nueva)
                validar_esquema_existente(nueva)
            # Solo se persiste tras la validación completa.
            guardar_ruta(nueva)
        except Exception as exc:
            usar_base_datos(activa)
            QMessageBox.critical(
                view, "No se cambió la base de datos",
                f"No se pudo validar la base seleccionada:\n\n{exc}\n\n"
                "La base activa y la ruta guardada se mantienen sin cambios.",
            )
            return

        QMessageBox.information(
            view, "Base de datos seleccionada",
            "La nueva base se validó y la ruta quedó guardada.\n\n"
            "Para evitar mezclar conexiones y operaciones, cierre y vuelva a abrir "
            "SistemaBalanza. La base nueva se utilizará en el próximo inicio.",
        )

    view.solicitar_cambio_base_datos.connect(cambiar_base_datos)
    view.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
