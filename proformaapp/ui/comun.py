"""Piezas de interfaz que usan varias pestañas: tablas, interruptor, formato de dinero, búsqueda sin tildes."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QHBoxLayout, QHeaderView, QProxyStyle,
                               QStyle, QTableWidget, QTableWidgetItem, QWidget)

from . import temas
from ..informes import dinero, numero  # noqa: F401 - las pestañas los toman de aquí
from ..modelo import iva_texto, leer_iva
from ..modelo import sin_tildes as normalizar  # noqa: F401


def leer_numero(texto: str, defecto: float) -> float:
    """Lo escrito en una celda: «1,5», «1.5» o lo que la app muestra («$ 1.234,50»). Si no se entiende, `defecto`."""
    t = texto.replace("$", "").replace(" ", "")
    if "," in t and t.rfind(",") > t.rfind("."):
        t = t.replace(".", "").replace(",", ".")
    else:
        t = t.replace(",", "")
    try:
        return float(t)
    except ValueError:
        return defecto


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
    s.lineEdit().setTextMargins(temas.S, 0, 0, 0)     # Qt ignora el «padding» de estos campos
    return s


class ComboIva(QComboBox):
    """Elegir el IVA de la lista o escribir un porcentaje (13, 12,5). Lo que no sea de 0 a 100 % se descarta."""

    def __init__(self, codigos: list[str]):
        super().__init__()
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        self.setCompleter(None)
        self.setMinimumWidth(190)
        self.setToolTip("Elija un IVA de la lista o escriba el porcentaje (por ejemplo 13 o 12,5) y presione Enter")
        for codigo in codigos:
            self.addItem(iva_texto(codigo), codigo)
        self.lineEdit().editingFinished.connect(self._escrito)

    def poner(self, codigo: str) -> None:
        i = self.findData(codigo)
        if i < 0:
            self.addItem(iva_texto(codigo), codigo)
            i = self.count() - 1
        self.setCurrentIndex(i)
        self.setEditText(self.itemText(i))

    def _escrito(self) -> None:
        self.poner(leer_iva(self.currentText()) or self.currentData())


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
        p.setBrush(QColor(temas.color("btn_exito" if self.isChecked() else "control")))
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
        if metrica in (QStyle.PM_LayoutHorizontalSpacing, QStyle.PM_LayoutVerticalSpacing):
            return temas.S
        if metrica in (QStyle.PM_LayoutLeftMargin, QStyle.PM_LayoutRightMargin, QStyle.PM_LayoutTopMargin,
                       QStyle.PM_LayoutBottomMargin):
            return temas.L
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
        verde = temas.color("btn_exito")
        p.setBrush(QColor(verde if activa else temas.mezcla(verde, temas.color("superficie"), 0.45)))
        p.drawRoundedRect(r, 4, 4)
        trazo = QPainterPath(QPointF(r.left() + r.width() * 0.22, r.top() + r.height() * 0.52))
        trazo.lineTo(r.left() + r.width() * 0.42, r.top() + r.height() * 0.72)
        trazo.lineTo(r.left() + r.width() * 0.78, r.top() + r.height() * 0.30)
        p.setPen(QPen(QColor("white"), 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        p.drawPath(trazo)
    else:
        p.setPen(QPen(QColor(temas.color("control" if activa else "borde")), 1.6))
        p.setBrush(QColor(temas.color("superficie")))
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
    t.verticalHeader().setDefaultSectionSize(temas.ALTO_FILA)
    t.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
    for c in range(1, len(columnas)):
        t.horizontalHeader().setSectionResizeMode(c, QHeaderView.ResizeToContents)
    return t


def abrir_archivo(ruta: Path) -> None:
    if shutil.which("gio"):
        subprocess.Popen(["gio", "open", str(ruta)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(ruta)))


def carpeta_proformas() -> Path:
    for n in ("Documentos", "Documents"):
        if (Path.home() / n).is_dir():
            return Path.home() / n / "Proformas"
    return Path.home() / "Proformas"


def pdf_a_imagen(pdf: Path, destino: Path, dpi: int = 150) -> bool:
    """Primera página de un PDF → imagen PNG (para usar una hoja membretada en PDF)."""
    from PySide6.QtCore import QCoreApplication, QSize
    from PySide6.QtPdf import QPdfDocument
    doc = QPdfDocument()
    doc.load(str(pdf))
    for _ in range(50):                            # en Windows la carga puede tardar un instante
        if doc.status() in (QPdfDocument.Status.Ready, QPdfDocument.Status.Error) and doc.pageCount():
            break
        QCoreApplication.processEvents()
    if doc.pageCount() < 1:
        return False
    tam = doc.pagePointSize(0)
    img = doc.render(0, QSize(round(tam.width() / 72 * dpi), round(tam.height() / 72 * dpi)))
    if img.isNull():
        return False
    from PySide6.QtGui import QColor, QImage, QPainter
    fondo = QImage(img.size(), QImage.Format_RGB32)       # fondo blanco (el PDF puede venir transparente)
    fondo.fill(QColor("white"))
    p = QPainter(fondo)
    p.drawImage(0, 0, img)
    p.end()
    return fondo.save(str(destino))
