"""Construye el ejecutable de Windows del Proformador (proformador.exe).

ESTO SE EJECUTA EN WINDOWS, no en Linux (PyInstaller no puede crear un .exe desde Linux).

Pasos en una PC con Windows:
  1) Instalar Python 3.12 de python.org (marcar «Add Python to PATH»).
  2) Abrir «Símbolo del sistema» (cmd) en la carpeta del proyecto.
  3)  py -m venv .venv
      .venv\\Scripts\\pip install -e ".[dev]" pyinstaller
      .venv\\Scripts\\python empaquetar\\construir_windows.py
  4) Resultado:  dist\\proformador-windows\\proformador.exe   (y un .zip para copiar a otra PC)

La otra PC con Windows no necesita instalar Python ni nada: se copia la carpeta y se abre proformador.exe.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
NOMBRE = "proformador"

SIN_USAR = ["tkinter", "pytest", "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.QtCharts",
            "PySide6.QtDataVisualization", "PySide6.QtBluetooth", "PySide6.QtSensors", "PySide6.QtSerialPort",
            "PySide6.QtDesigner", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtGraphs", "PySide6.QtQuick",
            "PySide6.QtQml", "PySide6.QtQuick3D", "PySide6.QtMultimedia", "PySide6.QtWebEngineCore",
            "PySide6.QtWebEngineWidgets", "PySide6.QtPositioning", "PySide6.QtWebSockets"]


def main() -> int:
    sys.path.insert(0, str(RAIZ))
    from proformaapp import __version__

    dist, build = RAIZ / "dist", RAIZ / "build"
    salida = dist / f"{NOMBRE}-windows"
    shutil.rmtree(build, ignore_errors=True)
    shutil.rmtree(salida, ignore_errors=True)

    icono = RAIZ / "empaquetar" / "icono.ico"
    args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--name", NOMBRE, "--windowed",
            "--onedir", "--paths", str(RAIZ), "--distpath", str(dist), "--workpath", str(build),
            "--specpath", str(build), "--collect-submodules", "openpyxl"]
    if icono.exists():
        args += ["--icon", str(icono)]
    for m in SIN_USAR:
        args += ["--exclude-module", m]
    args.append(str(RAIZ / "empaquetar" / "lanzador.py"))
    subprocess.run(args, check=True)

    # PyInstaller deja dist/proformador/ ; lo renombro a dist/proformador-windows/ y hago un zip
    carpeta = dist / NOMBRE
    if carpeta.exists():
        carpeta.rename(salida)
    zip_base = dist / f"{NOMBRE}-{__version__}-windows"
    if zip_base.with_suffix(".zip").exists():
        zip_base.with_suffix(".zip").unlink()
    shutil.make_archive(str(zip_base), "zip", root_dir=dist, base_dir=f"{NOMBRE}-windows")
    print(f"\nListo:\n  Carpeta:   {salida}\\{NOMBRE}.exe\n  Para copiar: {zip_base}.zip")
    return 0


if __name__ == "__main__":
    sys.exit(main())
