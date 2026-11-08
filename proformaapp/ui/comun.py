"""Piezas de interfaz que usan varias pestañas: tablas, interruptor, formato de dinero, búsqueda sin tildes."""

from __future__ import annotations

import shutil
import subprocess
import unicodedata
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDoubleSpinBox, QHBoxLayout, QHeaderView, QProxyStyle,
                               QStyle, QTableWidget, QTableWidgetItem, QWidget)

from .. import informes


def dinero(x: float) -> str:
    return informes.dinero(x)


def numero(x: float) -> str:
    """Cantidades, medidas y porcentajes: siempre con 2 decimales (1,50)."""
    return informes.numero(x)


class ItemOrdenable(QTableWidgetItem):
    """Celda que se ordena por una clave propia (texto sin tildes ni mayúsculas, o el valor numérico)."""

    def __init__(self, texto: str, clave):
        super().__init__(texto)
        self.clave = clave

    def __lt__(self, otro) -> bool:
        a, b = self.clave, getattr(otro, "clave", None)
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return a < b
        return str(a) < str(b)


def spin(minimo=0.0, maximo=1e7, decimales=2, sufijo="") -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setRange(minimo, maximo)
    s.setDecimals(decimales)
    s.setSuffix(sufijo)
    s.setMinimumWidth(90)
    return s


def item_texto(texto, editable=False, alinear_derecha=False) -> QTableWidgetItem:
    it = QTableWidgetItem(texto)
    if not editable:
        it.setFlags(it.flags() & ~Qt.ItemIsEditable)
    if alinear_derecha:
        it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
    return it


class Interruptor(QCheckBox):
    """Casilla con forma de interruptor deslizable (verde = sí)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(46, 26)

    def hitButton(self, pos) -> bool:          # todo el interruptor responde al clic
        return self.rect().contains(pos)

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        r = self.rect().adjusted(1, 1, -1, -1)
        p.setBrush(QColor("#2e7d32") if self.isChecked() else QColor("#cfd8dc"))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        d = r.height() - 6
        x = r.right() - d - 3 if self.isChecked() else r.left() + 3
        p.setBrush(QColor("white"))
        p.drawEllipse(x, r.top() + 3, d, d)
        p.end()


class EstiloCasillas(QProxyStyle):
    """Estilo «Fusion» (igual en Windows y Linux) con casillas propias, bien visibles: cuadro verde con ✓ blanco
    cuando está marcada y cuadro blanco con borde gris cuando no. Sirve para las QCheckBox y para las casillas de
    las listas (por ejemplo, las condiciones del servicio)."""

    LADO = 18

    def __init__(self):
        super().__init__("Fusion")

    def pixelMetric(self, metrica, opcion=None, widget=None):
        if metrica in (QStyle.PM_IndicatorWidth, QStyle.PM_IndicatorHeight):
            return self.LADO
        return super().pixelMetric(metrica, opcion, widget)

    def drawPrimitive(self, elemento, opcion, pintor, widget=None):
        if elemento not in (QStyle.PE_IndicatorCheckBox, QStyle.PE_IndicatorItemViewItemCheck):
            return super().drawPrimitive(elemento, opcion, pintor, widget)
        pintar_casilla(pintor, QRectF(opcion.rect), bool(opcion.state & QStyle.State_On),
                       bool(opcion.state & QStyle.State_Enabled))


def pintar_casilla(p: QPainter, rect: QRectF, marcada: bool, activa: bool = True) -> None:
    lado = min(rect.width(), rect.height(), EstiloCasillas.LADO)
    r = QRectF(0, 0, lado, lado)
    r.moveCenter(rect.center())
    r.adjust(1, 1, -1, -1)
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    if marcada:
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#2e7d32" if activa else "#a5d6a7"))
        p.drawRoundedRect(r, 4, 4)
        trazo = QPainterPath(QPointF(r.left() + r.width() * 0.22, r.top() + r.height() * 0.52))
        trazo.lineTo(r.left() + r.width() * 0.42, r.top() + r.height() * 0.72)
        trazo.lineTo(r.left() + r.width() * 0.78, r.top() + r.height() * 0.30)
        p.setPen(QPen(QColor("white"), 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        p.drawPath(trazo)
    else:
        p.setPen(QPen(QColor("#78909c" if activa else "#cfd8dc"), 1.6))
        p.setBrush(QColor("white"))
        p.drawRoundedRect(r, 4, 4)
    p.restore()


def centrado(w: QWidget) -> QWidget:
    caja = QWidget()
    lay = QHBoxLayout(caja)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(w, 0, Qt.AlignCenter)
    return caja


def tabla(columnas: list[str]) -> QTableWidget:
    t = QTableWidget(0, len(columnas))
    t.setHorizontalHeaderLabels(columnas)
    t.verticalHeader().setVisible(False)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setAlternatingRowColors(False)
    t.setShowGrid(False)
    t.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
    for c in range(1, len(columnas)):
        t.horizontalHeader().setSectionResizeMode(c, QHeaderView.ResizeToContents)
    return t


def abrir_archivo(ruta: Path) -> None:
    if shutil.which("gio"):
        subprocess.Popen(["gio", "open", str(ruta)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(ruta)))


def normalizar(texto: str) -> str:
    """Minúsculas y sin tildes, para buscar «diseno» y encontrar «DISEÑO»."""
    t = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def carpeta_proformas() -> Path:
    for n in ("Documentos", "Documents"):
        if (Path.home() / n).is_dir():
            return Path.home() / n / "Proformas"
    return Path.home() / "Proformas"
