"""Minimal PySide6 app with embedded JupyterLab — smoke test."""

import sys

from PySide6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget

from jupyqt import EmbeddedJupyter


def main():
    app = QApplication(sys.argv)
    window = QMainWindow()
    window.setWindowTitle("jupyqt smoke test")
    window.resize(1200, 800)

    jupyter = EmbeddedJupyter()
    jupyter.shell.push({"greeting": "Hello from jupyqt!"})
    jupyter.start()

    central = QWidget()
    layout = QVBoxLayout(central)
    layout.addWidget(jupyter.widget())
    window.setCentralWidget(central)

    window.show()

    ret = app.exec()
    jupyter.shutdown()
    sys.exit(ret)


if __name__ == "__main__":
    main()
