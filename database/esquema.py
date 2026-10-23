"""
Creación del esquema de SQLite (tablas, índices, triggers y vistas).
"""

from database.conexion import obtener_conexion, transaccion

# Súbelo cuando cambies el esquema. Si la BD existente tiene otra versión,
# inicializar_base_datos() avisa en lugar de dejar tablas viejas a medias.
VERSION_ESQUEMA = 8

_AHORA_SQL = "strftime('%Y-%m-%dT%H:%M:%S','now','localtime')"


def _ddl_maestro(tabla, pk, campos):
    """Tabla maestra: campos propios + id_externo, activo y fechas."""

    return f"""
        CREATE TABLE IF NOT EXISTS {tabla} (
            {pk} INTEGER PRIMARY KEY AUTOINCREMENT,
            {campos},
            id_externo TEXT,
            activo INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1)),
            created_at TEXT NOT NULL DEFAULT ({_AHORA_SQL}),
            updated_at TEXT NOT NULL DEFAULT ({_AHORA_SQL})
        )"""


def _idx_externo(tabla):
    return f"""
        CREATE UNIQUE INDEX IF NOT EXISTS ux_{tabla}_id_externo
        ON {tabla}(id_externo) WHERE id_externo IS NOT NULL"""


MAESTROS = [
    ("vehiculos", "id_vehiculo", "placa TEXT NOT NULL UNIQUE"),
    ("carretas", "id_carreta", "placa TEXT NOT NULL UNIQUE"),
    (
        "conductores",
        "id_conductor",
        "nombre TEXT NOT NULL, dni TEXT, brevete TEXT NOT NULL UNIQUE, domicilio TEXT",
    ),
    (
        "proveedores",
        "id_proveedor",
        "nombre TEXT NOT NULL, ruc TEXT NOT NULL UNIQUE",
    ),
    (
        "transportistas",
        "id_transportista",
        "nombre TEXT NOT NULL, ruc TEXT NOT NULL UNIQUE",
    ),
    (
        "concesiones",
        "id_concesion",
        "nombre TEXT NOT NULL, codigo TEXT NOT NULL UNIQUE, "
        "distrito TEXT, provincia TEXT, departamento TEXT",
    ),
]

DDL_CONFIGURACION_LOTES = """
    CREATE TABLE IF NOT EXISTS configuracion_lotes (
        id_configuracion INTEGER PRIMARY KEY CHECK (id_configuracion = 1),
        proximo_correlativo INTEGER NOT NULL CHECK (proximo_correlativo > 0),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )"""

# INGRESO / CAMIÓN: solo datos comunes a todos sus lotes
DDL_PESAJES = """
    CREATE TABLE IF NOT EXISTS pesajes (
        id_pesaje INTEGER PRIMARY KEY AUTOINCREMENT,
        uuid_pesaje TEXT NOT NULL UNIQUE,
        ticket INTEGER NOT NULL UNIQUE,
        id_vehiculo INTEGER,
        id_carreta INTEGER,
        id_conductor INTEGER,
        id_transportista INTEGER,
        estado TEXT NOT NULL DEFAULT 'EN_PROCESO'
            CHECK (estado IN ('EN_PROCESO', 'CONFIRMADO', 'ANULADO')),
        fecha_confirmacion TEXT,
        motivo_anulacion TEXT,
        sincronizado INTEGER NOT NULL DEFAULT 0
            CHECK (sincronizado IN (0, 1)),
        fecha_sincronizacion TEXT,
        equipo TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (id_vehiculo) REFERENCES vehiculos(id_vehiculo),
        FOREIGN KEY (id_carreta) REFERENCES carretas(id_carreta),
        FOREIGN KEY (id_conductor) REFERENCES conductores(id_conductor),
        FOREIGN KEY (id_transportista)
            REFERENCES transportistas(id_transportista)
    )"""

# CAPTURAS FÍSICAS: cuelgan del ingreso (una captura puede ser tara de un
# lote y bruto del siguiente). Solo inserción.
DDL_REGISTROS = """
    CREATE TABLE IF NOT EXISTS pesajes_registros (
        id_registro INTEGER PRIMARY KEY AUTOINCREMENT,
        uuid_registro TEXT NOT NULL UNIQUE,
        id_pesaje INTEGER NOT NULL,
        secuencia INTEGER NOT NULL,
        peso INTEGER NOT NULL CHECK (peso > 0),
        fecha_hora TEXT NOT NULL,
        anulado INTEGER NOT NULL DEFAULT 0 CHECK (anulado IN (0, 1)),
        motivo_anulacion TEXT,
        FOREIGN KEY (id_pesaje) REFERENCES pesajes(id_pesaje),
        UNIQUE (id_pesaje, secuencia)
    )"""

# LOTES: todo lo propio del lote. Los pesos NO se guardan aquí.
DDL_LOTES = """
    CREATE TABLE IF NOT EXISTS pesajes_lotes (
        id_pesaje_lote INTEGER PRIMARY KEY AUTOINCREMENT,
        uuid_lote TEXT NOT NULL UNIQUE,
        id_pesaje INTEGER NOT NULL,
        orden INTEGER NOT NULL,
        lote TEXT NOT NULL UNIQUE,
        id_proveedor INTEGER NOT NULL,
        guia_proveedor TEXT,
        guia_transportista TEXT,
        id_concesion INTEGER,
        producto TEXT,
        procedencia TEXT,
        observacion TEXT,
        tipo_carga TEXT NOT NULL CHECK (tipo_carga IN ('SACO', 'GRANEL')),
        cantidad_sacos INTEGER,
        priorizar_analisis INTEGER NOT NULL DEFAULT 0
            CHECK (priorizar_analisis IN (0, 1)),
        id_registro_bruto INTEGER,
        id_registro_tara INTEGER,
        estado TEXT NOT NULL DEFAULT 'PENDIENTE'
            CHECK (estado IN ('PENDIENTE', 'COMPLETADO', 'ANULADO')),
        motivo_anulacion TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        CHECK (
            (tipo_carga = 'SACO' AND cantidad_sacos > 0)
            OR (tipo_carga = 'GRANEL' AND cantidad_sacos IS NULL)
        ),
        UNIQUE (id_pesaje, orden),
        FOREIGN KEY (id_pesaje) REFERENCES pesajes(id_pesaje),
        FOREIGN KEY (id_proveedor) REFERENCES proveedores(id_proveedor),
        FOREIGN KEY (id_concesion) REFERENCES concesiones(id_concesion),
        FOREIGN KEY (id_registro_bruto)
            REFERENCES pesajes_registros(id_registro),
        FOREIGN KEY (id_registro_tara)
            REFERENCES pesajes_registros(id_registro)
    )"""

DDL_HISTORIAL_ELIMINACIONES = """
    CREATE TABLE IF NOT EXISTS historial_eliminaciones (
        id_historial INTEGER PRIMARY KEY AUTOINCREMENT,
        tipo_entidad TEXT NOT NULL CHECK (tipo_entidad IN ('LOTE', 'TICKET')),
        id_entidad_original INTEGER NOT NULL,
        ticket INTEGER,
        lote TEXT,
        motivo TEXT NOT NULL,
        datos_json TEXT NOT NULL,
        eliminado_en TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime'))
    )"""

DDL_HISTORIAL_CORRECCIONES_PESAJE = """
    CREATE TABLE IF NOT EXISTS historial_correcciones_pesaje (
        id_correccion INTEGER PRIMARY KEY AUTOINCREMENT,
        id_pesaje INTEGER NOT NULL,
        id_registro INTEGER NOT NULL,
        id_pesaje_lote INTEGER NOT NULL,
        tipo TEXT NOT NULL CHECK (tipo IN ('BRUTO', 'TARA')),
        peso_anterior INTEGER NOT NULL CHECK (peso_anterior > 0),
        peso_nuevo INTEGER NOT NULL CHECK (peso_nuevo > 0),
        fecha_hora_anterior TEXT,
        fecha_hora_nueva TEXT,
        motivo TEXT NOT NULL CHECK (length(trim(motivo)) > 0),
        fecha_hora TEXT NOT NULL,
        FOREIGN KEY (id_pesaje) REFERENCES pesajes(id_pesaje),
        FOREIGN KEY (id_registro) REFERENCES pesajes_registros(id_registro),
        FOREIGN KEY (id_pesaje_lote) REFERENCES pesajes_lotes(id_pesaje_lote)
    )"""

INDICES = [
    "CREATE INDEX IF NOT EXISTS ix_pesajes_estado ON pesajes(estado)",
    """CREATE INDEX IF NOT EXISTS ix_pesajes_sync
       ON pesajes(sincronizado, estado)""",
    "CREATE INDEX IF NOT EXISTS ix_lotes_pesaje ON pesajes_lotes(id_pesaje)",
    """CREATE INDEX IF NOT EXISTS ix_registros_pesaje
       ON pesajes_registros(id_pesaje)""",
    """CREATE INDEX IF NOT EXISTS ix_correcciones_registro
       ON historial_correcciones_pesaje(id_registro, id_correccion)""",
]

# Las capturas son solo de inserción (se puede marcar 'anulado', nada más)
TRIGGERS = [
    """CREATE TRIGGER IF NOT EXISTS trg_registros_sin_delete
       BEFORE DELETE ON pesajes_registros
       BEGIN
           SELECT RAISE(ABORT,
               'pesajes_registros es solo de insercion: use anulado=1');
       END""",
    """CREATE TRIGGER IF NOT EXISTS trg_registros_sin_update
       BEFORE UPDATE OF id_pesaje, secuencia, peso, fecha_hora
       ON pesajes_registros
       BEGIN
           SELECT RAISE(ABORT,
               'las capturas no se pueden modificar: anule y capture de nuevo');
       END""",
]

# Se recrea siempre (es barata) para que siga al esquema.
VISTA_LOTES = """
    CREATE VIEW v_lotes_detalle AS
    SELECT
        pl.id_pesaje_lote,
        pl.uuid_lote,
        pl.id_pesaje,
        p.uuid_pesaje,
        p.ticket,
        p.estado AS estado_ingreso,
        p.fecha_confirmacion,
        pl.orden,
        pl.lote,
        pl.tipo_carga,
        pl.cantidad_sacos,
        pl.priorizar_analisis,
        pl.guia_proveedor,
        pl.guia_transportista,
        pl.procedencia,
        pl.observacion,
        pr.id_proveedor,
        pr.nombre AS proveedor,
        pr.ruc AS ruc_proveedor,
        co.id_concesion,
        co.nombre AS concesion,
        co.codigo AS codigo_concesion,
        co.distrito AS distrito_concesion,
        co.provincia AS provincia_concesion,
        co.departamento AS departamento_concesion,
        ve.placa AS placa,
        ca.placa AS carreta,
        cd.nombre AS chofer,
        cd.dni AS dni_chofer,
        cd.brevete AS brevete,
        cd.domicilio AS domicilio_chofer,
        tr.nombre AS transportista,
        tr.ruc AS ruc_transportista,
        COALESCE(
            (SELECT hc.peso_nuevo FROM historial_correcciones_pesaje hc
              WHERE hc.id_registro = rb.id_registro
              ORDER BY hc.id_correccion DESC LIMIT 1),
            rb.peso
        ) AS peso_bruto,
        COALESCE(
            (SELECT hc.fecha_hora_nueva FROM historial_correcciones_pesaje hc
              WHERE hc.id_registro = rb.id_registro
                AND hc.fecha_hora_nueva IS NOT NULL
              ORDER BY hc.id_correccion DESC LIMIT 1),
            rb.fecha_hora
        ) AS fecha_bruto,
        COALESCE(
            (SELECT hc.peso_nuevo FROM historial_correcciones_pesaje hc
              WHERE hc.id_registro = rt.id_registro
              ORDER BY hc.id_correccion DESC LIMIT 1),
            rt.peso
        ) AS peso_tara,
        COALESCE(
            (SELECT hc.fecha_hora_nueva FROM historial_correcciones_pesaje hc
              WHERE hc.id_registro = rt.id_registro
                AND hc.fecha_hora_nueva IS NOT NULL
              ORDER BY hc.id_correccion DESC LIMIT 1),
            rt.fecha_hora
        ) AS fecha_tara,
        CASE
            WHEN rb.peso IS NOT NULL AND rt.peso IS NOT NULL
            THEN COALESCE(
                (SELECT hc.peso_nuevo FROM historial_correcciones_pesaje hc
                  WHERE hc.id_registro = rb.id_registro
                  ORDER BY hc.id_correccion DESC LIMIT 1),
                rb.peso
            ) - COALESCE(
                (SELECT hc.peso_nuevo FROM historial_correcciones_pesaje hc
                  WHERE hc.id_registro = rt.id_registro
                  ORDER BY hc.id_correccion DESC LIMIT 1),
                rt.peso
            )
        END AS peso_neto,
        pl.estado,
        pl.motivo_anulacion
    FROM pesajes_lotes pl
    JOIN pesajes p ON p.id_pesaje = pl.id_pesaje
    JOIN proveedores pr ON pr.id_proveedor = pl.id_proveedor
    LEFT JOIN concesiones co ON co.id_concesion = pl.id_concesion
    LEFT JOIN vehiculos ve ON ve.id_vehiculo = p.id_vehiculo
    LEFT JOIN carretas ca ON ca.id_carreta = p.id_carreta
    LEFT JOIN conductores cd ON cd.id_conductor = p.id_conductor
    LEFT JOIN transportistas tr ON tr.id_transportista = p.id_transportista
    LEFT JOIN pesajes_registros rb ON rb.id_registro = pl.id_registro_bruto
    LEFT JOIN pesajes_registros rt ON rt.id_registro = pl.id_registro_tara
"""


def inicializar_base_datos():
    """
    Crea las tablas si no existen.

    Si la BD ya existe con un esquema de otra versión, lanza un error
    claro (CREATE TABLE IF NOT EXISTS NO modifica tablas existentes).
    En desarrollo: borre data/balanza.db y vuelva a ejecutar.
    """

    conexion = obtener_conexion()

    try:
        version = conexion.execute("PRAGMA user_version").fetchone()[0]

        existe = conexion.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type = 'table' AND name = 'pesajes'"
        ).fetchone()

        if existe and version != VERSION_ESQUEMA:
            raise RuntimeError(
                f"La base de datos tiene un esquema distinto "
                f"(versión {version}, se esperaba {VERSION_ESQUEMA}).\n"
                f"Borre el archivo data/balanza.db y vuelva a iniciar."
            )

        conexion.execute("BEGIN IMMEDIATE")

        for tabla, pk, campos in MAESTROS:
            conexion.execute(_ddl_maestro(tabla, pk, campos))
            conexion.execute(_idx_externo(tabla))

        conexion.execute(DDL_CONFIGURACION_LOTES)
        conexion.execute(DDL_PESAJES)
        conexion.execute(DDL_REGISTROS)
        conexion.execute(DDL_LOTES)
        conexion.execute(DDL_HISTORIAL_ELIMINACIONES)
        conexion.execute(DDL_HISTORIAL_CORRECCIONES_PESAJE)

        for sentencia in INDICES + TRIGGERS:
            conexion.execute(sentencia)

        conexion.execute("DROP VIEW IF EXISTS v_lotes_detalle")
        conexion.execute(VISTA_LOTES)

        conexion.execute(f"PRAGMA user_version = {VERSION_ESQUEMA}")
        conexion.commit()

    except BaseException:
        if conexion.in_transaction:
            conexion.rollback()
        raise
    finally:
        conexion.close()


# ======================================================================
# DATOS DE PRUEBA (ficticios, solo para desarrollo)
# ======================================================================

_DATOS_PRUEBA = {
    "vehiculos": (
        "INSERT OR IGNORE INTO vehiculos (placa) VALUES (?)",
        [("B4V-905",), ("A8K-321",), ("T6P-742",), ("C9M-518",), ("F2R-637",)],
    ),
    "carretas": (
        "INSERT OR IGNORE INTO carretas (placa) VALUES (?)",
        [("C1R-458",), ("C2R-729",), ("C3R-615",), ("C4R-836",), ("C5R-247",)],
    ),
    "conductores": (
        "INSERT OR IGNORE INTO conductores (nombre, brevete) VALUES (?, ?)",
        [
            ("CHECALLA PAYE FACUNDO", "U41482246"),
            ("QUISPE MAMANI LUIS ALBERTO", "Q42581736"),
            ("CONDORI HUANCA MARCO ANTONIO", "C43829157"),
            ("MAMANI APAZA JORGE LUIS", "M44731582"),
            ("FLORES HUAYTA EDWIN", "F45982173"),
        ],
    ),
    "proveedores": (
        "INSERT OR IGNORE INTO proveedores (nombre, ruc) VALUES (?, ?)",
        [
            ("MINERA E INVERSIONES LUIS & CIELO E.I.R.L", "20613947575"),
            ("COMPAÑÍA MINERA ANDES DEL SUR S.A.C.", "20587412639"),
            ("MINERA SANTA ROSA E.I.R.L.", "20602581473"),
            ("MINERALES DEL PACÍFICO S.A.C.", "20481263751"),
            ("SERVICIOS MINEROS EL SOL E.I.R.L.", "20604729185"),
        ],
    ),
    "transportistas": (
        "INSERT OR IGNORE INTO transportistas (nombre, ruc) VALUES (?, ?)",
        [
            ("TRANSPORTES KORIANCAPRIA E.I.R.L.", "20612957593"),
            ("TRANSPORTES ANDINOS DEL SUR S.A.C.", "20563821479"),
            ("TRANSPORTES MINEROS DEL PACÍFICO E.I.R.L.", "20601847352"),
            ("LOGÍSTICA MINERA AREQUIPA S.A.C.", "20492731586"),
            ("TRANSPORTES SANTA CATALINA E.I.R.L.", "20603581724"),
        ],
    ),
    "concesiones": (
        "INSERT OR IGNORE INTO concesiones (nombre, codigo) VALUES (?, ?)",
        [
            ("SANTIAGO DE COMPOSTELA N° 6", "10000151Y01"),
            ("SANTA ROSA N° 12", "10000284Y02"),
            ("CERRO VERDE N° 8", "10000317Y03"),
            ("SAN ANTONIO N° 15", "10000426Y04"),
            ("NUEVA ESPERANZA N° 3", "10000539Y05"),
        ],
    ),
}


def insertar_datos_prueba():
    """Inserta maestros ficticios (INSERT OR IGNORE: no duplica)."""

    with transaccion() as cx:
        for sql, filas in _DATOS_PRUEBA.values():
            cx.executemany(sql, filas)
