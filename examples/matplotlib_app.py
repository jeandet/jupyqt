"""PySide6 app with embedded JupyterLab and matplotlib support.

Opens a pre-loaded notebook that demonstrates inline plotting.
Requires: matplotlib, matplotlib-inline (both optional deps).
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget

from jupyqt import EmbeddedJupyter

NOTEBOOK = Path(__file__).parent / "matplotlib_notebook.ipynb"


def main():
    app = QApplication(sys.argv)

    workdir = Path(tempfile.mkdtemp(prefix="jupyqt_mpl_"))
    shutil.copy(NOTEBOOK, workdir / "matplotlib_demo.ipynb")

    window = QMainWindow()
    window.setWindowTitle("jupyqt — matplotlib demo")
    window.resize(1200, 900)

    jupyter = EmbeddedJupyter()
    jupyter.start(cwd=str(workdir))

    central = QWidget()
    layout = QVBoxLayout(central)
    layout.addWidget(jupyter.widget())
    window.setCentralWidget(central)

    window.show()

    ret = app.exec()
    jupyter.shutdown()
    os.chdir(Path.home())
    shutil.rmtree(workdir, ignore_errors=True)
    sys.exit(ret)


if __name__ == "__main__":
    main()
