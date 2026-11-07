"""Construye el instalador .deb del Proformador (Zorin, Ubuntu, Mint, Debian…).

Uso, desde la carpeta del proyecto:   .venv/bin/python empaquetar/construir_deb.py
Resultado:                            dist/proformador_<versión>_amd64.deb

El programa va completo adentro (Python y Qt incluidos): en la otra máquina no hace falta instalar nada más.
Se instala en /opt/proformador, con su ícono en el menú de aplicaciones y el comando «proformador».
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
NOMBRE = "proformador"

# módulos de Qt que el Proformador no usa: se dejan fuera para que el instalador pese menos.
# OJO: NO se excluye QtGui/QtPdf (el PDF se genera con QPdfWriter).
SIN_USAR = ["tkinter", "pytest", "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.QtCharts",
            "PySide6.QtDataVisualization", "PySide6.QtBluetooth", "PySide6.QtSensors", "PySide6.QtSerialPort",
            "PySide6.QtDesigner", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtGraphs", "PySide6.QtQuick",
            "PySide6.QtQml", "PySide6.QtQuick3D", "PySide6.QtMultimedia", "PySide6.QtWebEngineCore",
            "PySide6.QtWebEngineWidgets", "PySide6.QtCharts", "PySide6.QtPositioning", "PySide6.QtWebSockets"]

ESCRITORIO = """[Desktop Entry]
Type=Application
Version=1.0
Name=Proformador Ágil
GenericName=Proformas de exhibidores
Comment=Proformas de exhibidores con receta de materiales, ganancia e informes
Exec=/opt/proformador/proformador
Icon=proformador
Terminal=false
Categories=Office;Finance;Spreadsheet;
Keywords=proforma;exhibidor;receta;materiales;costo;factura;
StartupWMClass=proformador
"""

POSTINST = """#!/bin/sh
set -e
update-desktop-database -q /usr/share/applications 2>/dev/null || true
gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor 2>/dev/null || true
exit 0
"""


def main() -> int:
    sys.path.insert(0, str(RAIZ))
    from proformaapp import __version__

    dist, build = RAIZ / "dist", RAIZ / "build"
    shutil.rmtree(build, ignore_errors=True)
    shutil.rmtree(dist / NOMBRE, ignore_errors=True)
    args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--name", NOMBRE, "--windowed",
            "--onedir", "--paths", str(RAIZ), "--distpath", str(dist), "--workpath", str(build),
            "--specpath", str(build), "--collect-submodules", "openpyxl"]
    for m in SIN_USAR:
        args += ["--exclude-module", m]
    args.append(str(RAIZ / "empaquetar" / "lanzador.py"))
    subprocess.run(args, check=True)

    paquete = build / "deb"
    shutil.rmtree(paquete, ignore_errors=True)
    shutil.copytree(dist / NOMBRE, paquete / "opt" / NOMBRE, symlinks=True)
    (paquete / "usr" / "bin").mkdir(parents=True)
    os.symlink(f"/opt/{NOMBRE}/{NOMBRE}", paquete / "usr" / "bin" / NOMBRE)
    apps = paquete / "usr" / "share" / "applications"
    apps.mkdir(parents=True)
    (apps / f"{NOMBRE}.desktop").write_text(ESCRITORIO, encoding="utf-8")
    iconos = paquete / "usr" / "share" / "icons" / "hicolor" / "scalable" / "apps"
    iconos.mkdir(parents=True)
    shutil.copy2(RAIZ / "empaquetar" / "icono.svg", iconos / f"{NOMBRE}.svg")

    tamano_kb = sum(p.stat().st_size for p in paquete.rglob("*") if p.is_file() and not p.is_symlink()) // 1024
    control = paquete / "DEBIAN"
    control.mkdir()
    (control / "control").write_text(f"""Package: {NOMBRE}
Version: {__version__}
Section: office
Priority: optional
Architecture: amd64
Installed-Size: {tamano_kb}
Depends: libc6 (>= 2.35), libxcb-cursor0, libxkbcommon-x11-0, libegl1, libgl1, libfontconfig1, libdbus-1-3, xdg-utils, libglib2.0-bin, libnss3, libxcomposite1, libxdamage1, libxrandr2, libxtst6, libxkbfile1
Recommends: gtk-update-icon-cache
Maintainer: Leninsodu <198639107+Leninsodu@users.noreply.github.com>
Description: Proformador Ágil - proformas de exhibidores
 Arma proformas de exhibidores a partir de una receta de materiales con su
 precio, calcula el costo y la ganancia, y genera informes en PDF para el
 cliente y en Excel para el control de costos. Módulos reutilizables,
 adicionales, varias empresas emisoras e importación desde Excel.
""", encoding="utf-8")
    (control / "postinst").write_text(POSTINST, encoding="utf-8")
    (control / "postrm").write_text(POSTINST, encoding="utf-8")
    for f in ("postinst", "postrm"):
        (control / f).chmod(0o755)
    for p in paquete.rglob("*"):
        if p.is_dir() and not p.is_symlink():
            p.chmod(0o755)
    destino = dist / f"{NOMBRE}_{__version__}_amd64.deb"
    destino.unlink(missing_ok=True)
    subprocess.run(["fakeroot", "dpkg-deb", "--build", "-Zxz", str(paquete), str(destino)], check=True)
    print(f"\nListo: {destino}  ({destino.stat().st_size / 1024 / 1024:.0f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
