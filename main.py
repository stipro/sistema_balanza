import sys

from PyQt6.QtWidgets import QApplication

from views.balanza_view import BalanzaView
from controllers.balanza_controller import BalanzaController
from database.database import inicializar_base_datos, insertar_datos_prueba

def main():

    # Crear SQLite y sus tablas
    inicializar_base_datos()
    # Cargar datos iniciales para pruebas
    insertar_datos_prueba()

    app = QApplication(
        sys.argv
    )

    view = BalanzaView()

    controller = BalanzaController(
        view
    )

    view.show()

    sys.exit(
        app.exec()
    )


if __name__ == "__main__":

    main()