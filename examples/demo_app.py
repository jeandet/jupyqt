"""Demo app: PySide6 UI with embedded JupyterLab and exposed widgets.

Starts in a temporary directory with a demo notebook pre-loaded.
The kernel namespace exposes the main window, a counter label,
and helper functions to manipulate the UI from notebook cells.
"""

import shutil
import sys
import tempfile
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from jupyqt import EmbeddedJupyter

DEMO_NOTEBOOK = Path(__file__).parent / "demo_notebook.ipynb"


def main():
    app = QApplication(sys.argv)

    workdir = Path(tempfile.mkdtemp(prefix="jupyqt_demo_"))
    shutil.copy(DEMO_NOTEBOOK, workdir / "demo.ipynb")

    window = QMainWindow()
    window.setWindowTitle("jupyqt demo")
    window.resize(1400, 900)

    sidebar = QWidget()
    sidebar.setFixedWidth(250)
    sidebar_layout = QVBoxLayout(sidebar)

    counter = [0]
    counter_label = QLabel(f"Counter: {counter[0]}")
    counter_label.setStyleSheet("font-size: 24px; padding: 12px;")

    def increment():
        counter[0] += 1
        counter_label.setText(f"Counter: {counter[0]}")

    def reset():
        counter[0] = 0
        counter_label.setText(f"Counter: {counter[0]}")

    inc_button = QPushButton("Increment")
    inc_button.clicked.connect(increment)
    reset_button = QPushButton("Reset")
    reset_button.clicked.connect(reset)

    sidebar_layout.addWidget(counter_label)
    sidebar_layout.addWidget(inc_button)
    sidebar_layout.addWidget(reset_button)
    sidebar_layout.addStretch()

    jupyter = EmbeddedJupyter()
    jupyter.push({"working_dir": str(workdir)})
    jupyter.shell.run_cell(f"import os; os.chdir({str(workdir)!r})")
    jupyter.start()

    jupyter.push({
        "window": jupyter.wrap_qt(window),
        "counter_label": jupyter.wrap_qt(counter_label),
        "increment": increment,
        "reset": reset,
    })

    central = QWidget()
    layout = QHBoxLayout(central)
    layout.addWidget(sidebar)
    layout.addWidget(jupyter.widget(), stretch=1)
    window.setCentralWidget(central)

    window.show()

    ret = app.exec()
    jupyter.shutdown()
    shutil.rmtree(workdir, ignore_errors=True)
    sys.exit(ret)


if __name__ == "__main__":
    main()
