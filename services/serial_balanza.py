import serial


class SerialBalanza:

    def __init__(self, puerto, baudrate=9600, timeout=0.1):
        self.puerto = puerto
        self.baudrate = baudrate
        self.timeout = timeout

        self.serial = None

    # CONECTAR
    def conectar(self):

        self.serial = serial.Serial(
            port=self.puerto,
            baudrate=self.baudrate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=self.timeout,
        )

        # Igual que el programa original
        self.serial.dtr = True
        self.serial.rts = True

        self.serial.reset_input_buffer()

    # ESTADO
    def esta_conectada(self):

        return self.serial is not None and self.serial.is_open

    # DATOS DISPONIBLES
    def hay_datos(self):

        if not self.esta_conectada():

            return False

        return self.serial.in_waiting > 0

    # LEER
    def leer(self):

        if not self.esta_conectada():

            return ""

        cantidad = self.serial.in_waiting

        if cantidad <= 0:

            return ""

        datos = self.serial.read(cantidad)

        if not datos:

            return ""

        return datos.decode("ascii", errors="ignore")

    # CERRAR
    def cerrar(self):

        if self.serial:

            try:

                if self.serial.is_open:

                    self.serial.close()

            except Exception:

                pass

        self.serial = None
