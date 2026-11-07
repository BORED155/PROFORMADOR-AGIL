import os

import pytest
from openpyxl import Workbook

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def excel(tmp_path):
    """Excel inventado con el mismo formato que el del usuario (RECETA, PROFORMA y una hoja de cliente)."""
    wb = Workbook()
    pf = wb.active
    pf.title = "PROFORMA"
    rec = wb.create_sheet("RECETA")
    rec["A1"], rec["A2"], rec["B2"] = "GENERALIDADES", "ITEM", "VALOR UNITARIO"
    materiales = [("TABLERO PRUEBA", 100), ("LED PRUEBA", 10), ("DISEÑO", 50), ("INVERSION", 50)]
    for f, (n, p) in enumerate(materiales, 3):
        rec.cell(f, 1, n)
        rec.cell(f, 2, p)
    rec.cell(7, 1, "TOTAL MIXTO")
    # módulo A en la columna D, módulo B en la G (como en el Excel real)
    rec["D1"], rec["D2"], rec["G1"], rec["G2"] = "MODULO ALFA", "CANT", "MODULO BETA", "CANT"
    for f, (a, b) in enumerate([(2, 1), (3, 0), ("=1*2", 1), (1, 1)], 3):
        rec.cell(f, 4, a)
        rec.cell(f, 7, b)
    pf["A6"], pf["C6"], pf["D6"], pf["E6"], pf["F6"], pf["H6"] = ("MÓDULO ALFA DE PRUEBA", "- 1 BASE\n- LUCES", 1.2,
                                                                  2.4, 0.6, "=+RECETA!E29")
    cli = wb.create_sheet("CLIENTE X")
    for f, (k, v) in enumerate([("CLIENTE :", "EMPRESA FICTICIA S.A."), ("RUC:", "1799999999001"),
                                ("DIRECCIÓN :", "Calle Falsa 123"), ("CONTACTO :", "0990000000"),
                                ("CORREO :", "compras@ejemplo.com")], 1):
        cli.cell(f, 2, k)
        cli.cell(f, 3, v)
    ruta = tmp_path / "proforma prueba.xlsx"
    wb.save(ruta)
    return ruta


@pytest.fixture(autouse=True)
def sin_ventanas_emergentes(monkeypatch):
    """En las pruebas los avisos no esperan un clic: se responden solos (Sí / Aceptar)."""
    from PySide6.QtWidgets import QMessageBox
    vistos = []

    def responder(respuesta):
        def f(*a, **k):
            vistos.append(a[2] if len(a) > 2 else "")
            return respuesta
        return f

    monkeypatch.setattr(QMessageBox, "warning", responder(QMessageBox.Ok))
    monkeypatch.setattr(QMessageBox, "information", responder(QMessageBox.Ok))
    monkeypatch.setattr(QMessageBox, "question", responder(QMessageBox.Yes))
    return vistos
