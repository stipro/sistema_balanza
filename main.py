import sys
from PyQt6.QtWidgets import QApplication
from database.esquema import inicializar_base_datos, insertar_datos_prueba
from views.balanza_view import BalanzaView
from controllers.balanza_controller import BalanzaController


def main():
    app = QApplication(sys.argv)
    # Crear SQLite y sus tablas
    inicializar_base_datos()  # crea el esquema v3 (o avisa si hay versión vieja)
    # Cargar datos iniciales para pruebas
    insertar_datos_prueba()  # SOLO en desarrollo

    view = BalanzaView()

    controller = BalanzaController(view)

    view.show()

    sys.exit(app.exec())


if __name__ == "__main__":

    main()
