"""
Conexión a SQLite y manejo de transacciones.

- obtener_conexion(): abre una conexión con los PRAGMA correctos.
- lectura(): contexto para consultas (abre y cierra la conexión).
- transaccion(): contexto para escrituras (BEGIN IMMEDIATE + commit/rollback).

Si a lectura() o transaccion() se les pasa una conexión ya abierta, la usan
tal cual y NO hacen commit: así varias operaciones comparten UNA transacción.
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "balanza.db"

_ruta_actual = DB_PATH


def usar_base_datos(ruta):
    """Cambia la BD en uso (sirve para pruebas con una BD temporal)."""
    global _ruta_actual
    _ruta_actual = Path(ruta)


def ruta_base_datos():
    return _ruta_actual


def ahora():
    """Fecha/hora actual en formato ISO, sin microsegundos."""
    return datetime.now().isoformat(timespec="seconds")


def obtener_conexion():
    """
    Abre una conexión a SQLite.

    - isolation_level=None: las transacciones las controlamos nosotros.
    - foreign_keys=ON: respeta las claves foráneas.
    - WAL + synchronous=FULL: resisten cortes de luz.
    """

    ruta = _ruta_actual
    ruta.parent.mkdir(parents=True, exist_ok=True)

    conexion = sqlite3.connect(ruta, timeout=10, isolation_level=None)
    conexion.row_factory = sqlite3.Row

    conexion.execute("PRAGMA foreign_keys = ON")
    conexion.execute("PRAGMA journal_mode = WAL")
    conexion.execute("PRAGMA synchronous = FULL")

    return conexion


@contextmanager
def lectura(conexion=None):
    """Para consultas. Si se pasa una conexión, la reutiliza sin cerrarla."""

    if conexion is not None:
        yield conexion
        return

    cx = obtener_conexion()
    try:
        yield cx
    finally:
        cx.close()


@contextmanager
def transaccion(conexion=None):
    """
    Para escrituras. Sin conexión: abre una, hace BEGIN IMMEDIATE y
    commit al terminar (o rollback si hay error).
    Con conexión: la reutiliza; quien la abrió decide el commit.
    """

    if conexion is not None:
        yield conexion
        return

    cx = obtener_conexion()
    try:
        cx.execute("BEGIN IMMEDIATE")
        yield cx
        cx.commit()
    except BaseException:
        if cx.in_transaction:
            cx.rollback()
        raise
    finally:
        cx.close()
