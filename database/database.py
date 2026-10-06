import sqlite3
from pathlib import Path

# ==========================================================
# UBICACIÓN DE LA BASE DE DATOS
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "balanza.db"

# CONEXIÓN
def obtener_conexion():
    """
    Obtiene una conexión a SQLite.
    """

    DATA_DIR.mkdir(parents=True,exist_ok=True)
    conexion = sqlite3.connect(DB_PATH)
    conexion.execute("PRAGMA foreign_keys = ON")
    return conexion

# CREAR TABLAS
def inicializar_base_datos():
    """
    Crea las tablas necesarias si todavía no existen.
    """
    conexion = obtener_conexion()
    try:
        cursor = conexion.cursor()

        # VEHÍCULOS
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS vehiculos (
                id_vehiculo INTEGER PRIMARY KEY AUTOINCREMENT,
                placa TEXT NOT NULL UNIQUE
            )
            """)

        # CARRETAS
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS carretas (
                id_carreta INTEGER PRIMARY KEY AUTOINCREMENT,
                placa TEXT NOT NULL UNIQUE
            )
            """)

        # CONDUCTORES
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS conductores (
                id_conductor INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL,
                brevete TEXT NOT NULL UNIQUE
            )
            """)

        # PROVEEDORES
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS proveedores (
                id_proveedor INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL,
                ruc TEXT NOT NULL UNIQUE
            )
            """)

        # TRANSPORTISTAS
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS transportistas (
                id_transportista INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL,
                ruc TEXT NOT NULL UNIQUE
            )
            """)

        # CONCESIONES
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS concesiones (
                id_concesion INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL,
                codigo TEXT NOT NULL UNIQUE
            )
            """)

        # PESAJES
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS pesajes (
                id_pesaje INTEGER PRIMARY KEY AUTOINCREMENT,
                uuid_pesaje TEXT NOT NULL UNIQUE,
                ticket TEXT NOT NULL UNIQUE,
                id_vehiculo INTEGER NOT NULL,
                id_carreta INTEGER,
                id_conductor INTEGER,
                id_proveedor INTEGER,
                id_transportista INTEGER,
                id_concesion INTEGER,
                guia_proveedor TEXT,
                guia_transportista TEXT,
                procedencia TEXT,
                producto TEXT,
                observacion TEXT,
                estado TEXT NOT NULL DEFAULT 'NUEVO'
                    CHECK (
                        estado IN (
                            'NUEVO',
                            'EN_PROCESO',
                            'COMPLETADO',
                            'ANULADO'
                        )
                    ),
                sincronizado INTEGER NOT NULL DEFAULT 0
                    CHECK (sincronizado IN (0, 1)),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                                FOREIGN KEY (id_vehiculo)
                    REFERENCES vehiculos(id_vehiculo),

                FOREIGN KEY (id_carreta)
                    REFERENCES carretas(id_carreta),

                FOREIGN KEY (id_conductor)
                    REFERENCES conductores(id_conductor),

                FOREIGN KEY (id_proveedor)
                    REFERENCES proveedores(id_proveedor),

                FOREIGN KEY (id_transportista)
                    REFERENCES transportistas(id_transportista),

                FOREIGN KEY (id_concesion)
                    REFERENCES concesiones(id_concesion)
            )""")

        # PESAJES LOTES
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS pesajes_lotes (
                id_pesaje_lote INTEGER PRIMARY KEY AUTOINCREMENT,
                id_pesaje INTEGER NOT NULL,
                lote TEXT NOT NULL,
                cantidad_sacos INTEGER,
                orden INTEGER NOT NULL,
                id_registro_bruto INTEGER,
                id_registro_tara INTEGER,
                peso_bruto REAL,
                peso_tara REAL,
                peso_neto REAL,
                estado TEXT NOT NULL DEFAULT 'PENDIENTE'
                    CHECK (
                        estado IN (
                            'PENDIENTE',
                            'COMPLETADO',
                            'ANULADO'
                        )
                    ),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (id_pesaje)
                    REFERENCES pesajes(id_pesaje)
                    ON DELETE CASCADE)""")

        # PESAJES REGISTROS
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS pesajes_registros (
                id_registro INTEGER PRIMARY KEY AUTOINCREMENT,
                id_pesaje INTEGER NOT NULL,
                secuencia INTEGER NOT NULL,
                peso REAL NOT NULL,
                fecha_hora TEXT NOT NULL,
                sincronizado INTEGER NOT NULL DEFAULT 0
                    CHECK (
                        sincronizado IN (0, 1)
                    ),
                FOREIGN KEY (id_pesaje)
                    REFERENCES pesajes(id_pesaje)
                    ON DELETE CASCADE,
                UNIQUE (id_pesaje,secuencia))""")
        conexion.commit()
    finally:
        conexion.close()

def insertar_datos_prueba():
    conexion = obtener_conexion()
    try:
        cursor = conexion.cursor()

        # VEHÍCULOS
        cursor.executemany(
            """
            INSERT OR IGNORE INTO vehiculos (placa)
            VALUES (?)
            """,
            [
                ("B4V-905",),
                ("A8K-321",),
                ("T6P-742",),
                ("C9M-518",),
                ("F2R-637",),
            ]
        )

        # ==================================================
        # CARRETAS
        # ==================================================

        cursor.executemany(
            """
            INSERT OR IGNORE INTO carretas (placa)
            VALUES (?)
            """,
            [
                ("C1R-458",),
                ("C2R-729",),
                ("C3R-615",),
                ("C4R-836",),
                ("C5R-247",),
            ]
        )

        # ==================================================
        # CONDUCTORES
        # ==================================================

        cursor.executemany(
            """
            INSERT OR IGNORE INTO conductores (
                nombre,
                brevete
            )
            VALUES (?, ?)
            """,
            [
                ("CHECALLA PAYE FACUNDO", "U41482246"),
                ("QUISPE MAMANI LUIS ALBERTO", "Q42581736"),
                ("CONDORI HUANCA MARCO ANTONIO", "C43829157"),
                ("MAMANI APAZA JORGE LUIS", "M44731582"),
                ("FLORES HUAYTA EDWIN", "F45982173"),
            ]
        )

        # ==================================================
        # PROVEEDORES
        # ==================================================

        cursor.executemany(
            """
            INSERT OR IGNORE INTO proveedores (
                nombre,
                ruc
            )
            VALUES (?, ?)
            """,
            [
                (
                    "MINERA E INVERSIONES LUIS & CIELO E.I.R.L",
                    "20613947575"
                ),
                (
                    "COMPAÑÍA MINERA ANDES DEL SUR S.A.C.",
                    "20587412639"
                ),
                (
                    "MINERA SANTA ROSA E.I.R.L.",
                    "20602581473"
                ),
                (
                    "MINERALES DEL PACÍFICO S.A.C.",
                    "20481263751"
                ),
                (
                    "SERVICIOS MINEROS EL SOL E.I.R.L.",
                    "20604729185"
                ),
            ]
        )

        # ==================================================
        # TRANSPORTISTAS
        # ==================================================

        cursor.executemany(
            """
            INSERT OR IGNORE INTO transportistas (
                nombre,
                ruc
            )
            VALUES (?, ?)
            """,
            [
                (
                    "TRANSPORTES KORIANCAPRIA E.I.R.L.",
                    "20612957593"
                ),
                (
                    "TRANSPORTES ANDINOS DEL SUR S.A.C.",
                    "20563821479"
                ),
                (
                    "TRANSPORTES MINEROS DEL PACÍFICO E.I.R.L.",
                    "20601847352"
                ),
                (
                    "LOGÍSTICA MINERA AREQUIPA S.A.C.",
                    "20492731586"
                ),
                (
                    "TRANSPORTES SANTA CATALINA E.I.R.L.",
                    "20603581724"
                ),
            ]
        )

        # ==================================================
        # CONCESIONES
        # ==================================================

        cursor.executemany(
            """
            INSERT OR IGNORE INTO concesiones (
                nombre,
                codigo
            )
            VALUES (?, ?)
            """,
            [
                (
                    "SANTIAGO DE COMPOSTELA N° 6",
                    "10000151Y01"
                ),
                (
                    "SANTA ROSA N° 12",
                    "10000284Y02"
                ),
                (
                    "CERRO VERDE N° 8",
                    "10000317Y03"
                ),
                (
                    "SAN ANTONIO N° 15",
                    "10000426Y04"
                ),
                (
                    "NUEVA ESPERANZA N° 3",
                    "10000539Y05"
                ),
            ]
        )

        conexion.commit()

    finally:

        conexion.close()

def obtener_vehiculos():
    conexion = obtener_conexion()
    try:
        cursor = conexion.cursor()
        cursor.execute("""
            SELECT id_vehiculo, placa
            FROM vehiculos
            ORDER BY placa
        """)
        return cursor.fetchall()
    finally:
        conexion.close()

def obtener_carretas():
    conexion = obtener_conexion()
    try:
        cursor = conexion.cursor()
        cursor.execute("""
            SELECT id_carreta, placa
            FROM carretas
            ORDER BY placa
        """)
        return cursor.fetchall()
    finally:
        conexion.close()

def obtener_conductores():
    conexion = obtener_conexion()
    try:
        cursor = conexion.cursor()
        cursor.execute("""
            SELECT id_conductor, nombre, brevete
            FROM conductores
            ORDER BY nombre
        """)
        return cursor.fetchall()
    finally:
        conexion.close()

def obtener_proveedores():
    conexion = obtener_conexion()
    try:
        cursor = conexion.cursor()
        cursor.execute("""
            SELECT id_proveedor, nombre, ruc
            FROM proveedores
            ORDER BY nombre
        """)
        return cursor.fetchall()
    finally:
        conexion.close()

def obtener_transportistas():
    conexion = obtener_conexion()
    try:
        cursor = conexion.cursor()
        cursor.execute("""
            SELECT id_transportista, nombre, ruc
            FROM transportistas
            ORDER BY nombre
        """)
        return cursor.fetchall()
    finally:
        conexion.close()

def obtener_concesiones():
    conexion = obtener_conexion()
    try:
        cursor = conexion.cursor()
        cursor.execute("""
            SELECT id_concesion, nombre, codigo
            FROM concesiones
            ORDER BY nombre
        """)
        return cursor.fetchall()
    finally:
        conexion.close()