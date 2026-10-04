import sys

from PyQt6.QtWidgets import QApplication

from views.balanza_view import BalanzaView
from controllers.balanza_controller import BalanzaController


def main():

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