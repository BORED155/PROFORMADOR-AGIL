"""Arranque del Proformador."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QLibraryInfo, QLocale, QTimer, QTranslator
from PySide6.QtWidgets import QApplication, QMessageBox


def ejecutar(argumentos: list[str]) -> int:
    QLocale.setDefault(QLocale(QLocale.Spanish, QLocale.Ecuador))
    app = QApplication([sys.argv[0]] + argumentos)
    app.setApplicationName("Proformador")
    app.setDesktopFileName("proformador")
    traductor = QTranslator(app)
    if traductor.load("qtbase_es", QLibraryInfo.path(QLibraryInfo.TranslationsPath)):
        app.installTranslator(traductor)
    # una sola ventana a la vez: dos copias abiertas se pisan los datos al guardar
    from PySide6.QtCore import QLockFile
    from ..modelo import carpeta_datos
    candado = QLockFile(str(carpeta_datos() / "proformador.lock"))
    candado.setStaleLockTime(0)
    if not candado.tryLock(200):
        QMessageBox.information(None, "Proformador", "El Proformador ya está abierto.\n\nBusque su ventana en la barra "
                                                     "de tareas (no se abre una segunda copia para no perder datos).")
        return 0
    app._candado = candado

    # si algo falla, se muestra en pantalla en vez de fallar en silencio
    import traceback

    def avisar_error(tipo, valor, rastro):
        traceback.print_exception(tipo, valor, rastro)
        QMessageBox.warning(None, "Proformador: algo falló",
                            f"{valor}\n\nSi se repite, cuénteselo a quien le ayuda con el programa.\n\n"
                            + "".join(traceback.format_exception(tipo, valor, rastro))[-1500:])
    sys.excepthook = avisar_error

    from .ventana import VentanaPrincipal

    v = VentanaPrincipal()
    v.show()
    if not v.datos.materiales:
        def primera_vez():
            sugerido = sorted(Path.home().glob("Descargas/*roforma*.xlsx"))
            QMessageBox.information(v, "Bienvenido", "Para empezar, elija su Excel de proformas: de ahí se toman los "
                                                      "materiales con sus precios, los módulos con su receta, los "
                                                      "clientes y las fotos.")
            v.importar_excel(None if not sugerido else None)
        QTimer.singleShot(300, primera_vez)
    return app.exec()
