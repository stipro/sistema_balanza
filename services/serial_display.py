import serial


class SerialDisplay:

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

        self.serial.dtr = True
        self.serial.rts = True

        self.serial.reset_input_buffer()

    # ESTADO
    def esta_conectado(self):

        return self.serial is not None and self.serial.is_open

    # ENVIAR PESO
    def enviar_peso(self, peso):

        if not self.esta_conectado():

            return False

        peso = str(peso).strip()

        if not peso:

            return False

        # LÓGICA ACTUAL
        peso_invertido = peso[::-1]

        mensaje = "= " + peso_invertido

        self.serial.write(mensaje.encode("ascii"))

        self.serial.flush()

        return mensaje

    # CERRAR
    def cerrar(self):

        if self.serial:

            try:

                if self.serial.is_open:

                    self.serial.close()

            except Exception:

                pass

        self.serial = None
