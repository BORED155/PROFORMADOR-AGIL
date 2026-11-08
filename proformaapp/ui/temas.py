"""Aspecto de la app: una sola escala de espaciado y tres estilos. Los informes (PDF, Excel) no dependen de esto."""

from __future__ import annotations

import tempfile
from pathlib import Path
from string import Template

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPalette, QPixmap, QPolygonF
from PySide6.QtWidgets import QApplication, QWidget

# escala de espaciado (px): todo margen o separación sale de aquí
XS, S, M, L, XL = 4, 8, 12, 16, 24
ALTO_FILA = 32

TEMAS: dict[str, dict[str, str]] = {
    "claro": {
        "nombre": "Claro profesional", "fondo": "#F1F5F9", "superficie": "#FFFFFF", "superficie2": "#E2E8F0",
        "borde": "#CBD5E1", "control": "#7C8AA0", "texto": "#0F172A", "texto2": "#475569", "acento": "#1E40AF",
        "primario": "#1D4ED8", "sobre_primario": "#FFFFFF", "suave": "#DBEAFE",
        "sobre_suave": "#1E3A8A", "exito": "#15803D", "peligro": "#B91C1C", "aviso": "#B45309",
        "btn_exito": "#15803D", "btn_exito_hover": "#166534", "btn_peligro": "#B91C1C", "btn_peligro_hover": "#991B1B",
        "foco": "#1D4ED8",
    },
    "oscuro": {
        "nombre": "Oscuro grafito", "fondo": "#111827", "superficie": "#1F2937", "superficie2": "#374151",
        "borde": "#3F4B5C", "control": "#7F8A9B", "texto": "#F3F4F6", "texto2": "#BAC3CF", "acento": "#93C5FD",
        "primario": "#2563EB", "sobre_primario": "#FFFFFF", "suave": "#1E3A5F",
        "sobre_suave": "#DBEAFE", "exito": "#4ADE80", "peligro": "#FCA5A5", "aviso": "#FBBF24",
        "btn_exito": "#15803D", "btn_exito_hover": "#166534", "btn_peligro": "#B91C1C", "btn_peligro_hover": "#991B1B",
        "foco": "#93C5FD",
    },
    "papel": {
        "nombre": "Papel cálido", "fondo": "#EFE9DD", "superficie": "#FBF7EF", "superficie2": "#E6DECF",
        "borde": "#D6CCB8", "control": "#8F846F", "texto": "#2B2620", "texto2": "#5F5646", "acento": "#0B5F5F",
        "primario": "#0F6B6B", "sobre_primario": "#FFFFFF", "suave": "#D3E6E0",
        "sobre_suave": "#0A4C4C", "exito": "#2F6B1F", "peligro": "#A12A1C", "aviso": "#8A4B00",
        "btn_exito": "#2F6B1F", "btn_exito_hover": "#255717", "btn_peligro": "#A12A1C", "btn_peligro_hover": "#862216",
        "foco": "#0F6B6B",
    },
    "salvia": {
        "nombre": "Verde salvia", "fondo": "#E7ECE6", "superficie": "#F7F9F5", "superficie2": "#DBE3D9",
        "borde": "#C3CEC1", "control": "#7A8878", "texto": "#1E2A22", "texto2": "#4C5B50", "acento": "#2F4B7C",
        "primario": "#35558A", "sobre_primario": "#FFFFFF", "suave": "#D8E2EE",
        "sobre_suave": "#24395F", "exito": "#2B6B35", "peligro": "#A32A2A", "aviso": "#8A4F00",
        "btn_exito": "#2B6B35", "btn_exito_hover": "#225629", "btn_peligro": "#A32A2A", "btn_peligro_hover": "#872222",
        "foco": "#35558A",
    },
    "contraste": {
        "nombre": "Alto contraste", "fondo": "#000000", "superficie": "#0D0D0D", "superficie2": "#2A2A2A",
        "borde": "#8C8C8C", "control": "#B0B0B0", "texto": "#FFFFFF", "texto2": "#E0E0E0", "acento": "#7FD8FF",
        "primario": "#0A58CA", "sobre_primario": "#FFFFFF", "suave": "#3A3200",
        "sobre_suave": "#FFF3B0", "exito": "#5CFF8F", "peligro": "#FF9C9C", "aviso": "#FFD166",
        "btn_exito": "#0F7A33", "btn_exito_hover": "#0B6128", "btn_peligro": "#C01818", "btn_peligro_hover": "#A01212",
        "foco": "#FFE14D",
    },
}

_actual = "claro"
_flechas = tempfile.TemporaryDirectory(prefix="proformador-")      # Qt lee las flechas de archivos; se borran al salir


def color(token: str) -> str:
    return TEMAS[_actual][token]


def mezcla(a: str, b: str, proporcion: float) -> str:
    """El color `a` con el `proporcion` de opacidad sobre `b`."""
    ca, cb = QColor(a), QColor(b)
    canal = [round(x * proporcion + y * (1 - proporcion)) for x, y in zip(ca.getRgb()[:3], cb.getRgb()[:3])]
    return QColor(*canal).name()


def botones_neutros(t: dict[str, str]) -> dict[str, str]:
    """Los botones sin acción de crear o borrar: el color principal del estilo, más oscuro."""
    return {"btn_neutro": mezcla(t["primario"], "#000000", 0.75), "btn_neutro_hover": mezcla(t["primario"], "#000000", 0.62)}


def rol(w: QWidget, nombre: str) -> None:
    """Función del texto o cuadro: «ayuda», «nota», «subtitulo», «foto», «separador»."""
    _marcar(w, "rol", nombre)


def tono(w: QWidget, nombre: str) -> None:
    """Color según el significado: «acento», «exito», «peligro», «aviso», «neutro»."""
    _marcar(w, "tono", nombre)


def _marcar(w: QWidget, propiedad: str, valor: str) -> None:
    if w.property(propiedad) == valor:
        return
    w.setProperty(propiedad, valor)
    w.style().unpolish(w)
    w.style().polish(w)


def _flecha(nombre: str, tinte: str, arriba: bool) -> str:
    img = QPixmap(20, 20)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(tinte))
    p.drawPolygon(QPolygonF([QPointF(3, 15), QPointF(17, 15), QPointF(10, 5)] if arriba else
                            [QPointF(3, 5), QPointF(17, 5), QPointF(10, 15)]))
    p.end()
    ruta = Path(_flechas.name) / nombre
    img.save(str(ruta))
    return ruta.as_posix()


def _paleta(t: dict[str, str]) -> QPalette:
    pal = QPalette()
    for papel, token in ((QPalette.Window, "fondo"), (QPalette.WindowText, "texto"), (QPalette.Base, "superficie"),
                         (QPalette.AlternateBase, "fondo"), (QPalette.Text, "texto"), (QPalette.Button, "superficie"),
                         (QPalette.ButtonText, "texto"), (QPalette.ToolTipBase, "superficie"),
                         (QPalette.ToolTipText, "texto"), (QPalette.PlaceholderText, "texto2"),
                         (QPalette.Highlight, "primario"), (QPalette.HighlightedText, "sobre_primario"),
                         (QPalette.Link, "acento")):
        pal.setColor(papel, QColor(t[token]))
    for papel in (QPalette.Text, QPalette.WindowText, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, papel, QColor(t["texto2"]))
    return pal


_QSS = Template("""
QWidget { font-size: 13px; }
QMainWindow, QDialog, QMessageBox { background: $fondo; }
QToolTip { background: $superficie; color: $texto; border: 1px solid $borde; padding: 4px 8px; }

QTabWidget::pane { border: 1px solid $borde; border-radius: 8px; background: $superficie; top: -1px; }
QTabBar::tab { background: $superficie2; color: $texto2; border: 1px solid $borde; padding: 8px 16px; margin-right: 4px;
               border-top-left-radius: 8px; border-top-right-radius: 8px; }
QTabBar::tab:hover { color: $texto; }
QTabBar::tab:selected { background: $superficie; color: $acento; font-weight: bold; border-bottom-color: $superficie; }

QTableWidget, QListWidget, QPlainTextEdit { border: 1px solid $borde; border-radius: 8px; background: $superficie;
                                            color: $texto; selection-background-color: $primario;
                                            selection-color: $sobre_primario; }
QTableWidget::item { padding: 0 4px; }
QListWidget::item { padding: 4px; }
QListWidget#condiciones { selection-background-color: $suave; selection-color: $sobre_suave; }
QHeaderView::section { background: $superficie; color: $texto; border: none; border-bottom: 1px solid $borde;
                       padding: 8px; font-weight: bold; }
QTableView QLineEdit { padding: 0 4px; min-height: 0; border: 1px solid $foco; border-radius: 0; }

QLineEdit, QComboBox, QDoubleSpinBox, QSpinBox, QDateEdit { border: 1px solid $control; border-radius: 6px; padding: 4px 8px;
                                                            min-height: 22px; background: $superficie; color: $texto;
                                                            selection-background-color: $primario;
                                                            selection-color: $sobre_primario; }
QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus, QSpinBox:focus, QDateEdit:focus, QPlainTextEdit:focus {
    border: 2px solid $foco; padding: 3px 7px; }
QPlainTextEdit:focus { padding: 0; }
QLineEdit:disabled, QComboBox:disabled, QDoubleSpinBox:disabled, QSpinBox:disabled {
    background: $superficie2; color: $texto2; border-color: $borde; }
QAbstractSpinBox QLineEdit, QComboBox QLineEdit, QDateEdit QLineEdit {
    border: none; padding: 0; min-height: 0; background: transparent; }

QComboBox#estilo { combobox-popup: 0; }
QComboBox::drop-down, QDateEdit::drop-down { border: none; width: 24px; }
QComboBox::down-arrow, QDateEdit::down-arrow { image: url("$flecha_abajo"); width: 10px; height: 10px; }
QComboBox QAbstractItemView { background: $superficie; color: $texto; border: 1px solid $borde;
                              selection-background-color: $primario; selection-color: $sobre_primario; }
QAbstractSpinBox::up-button { subcontrol-origin: border; subcontrol-position: top right; width: 20px; border: none; }
QAbstractSpinBox::down-button { subcontrol-origin: border; subcontrol-position: bottom right; width: 20px; border: none; }
QAbstractSpinBox::up-arrow { image: url("$flecha_arriba"); width: 8px; height: 8px; }
QAbstractSpinBox::down-arrow { image: url("$flecha_abajo"); width: 8px; height: 8px; }

QCalendarWidget QWidget { background: $superficie; color: $texto; }
QCalendarWidget QToolButton { background: $superficie2; color: $texto; padding: 4px 8px; border: none; }
QCalendarWidget QAbstractItemView { selection-background-color: $primario; selection-color: $sobre_primario; }
QMenu { background: $superficie; color: $texto; border: 1px solid $borde; }
QMenu::item { padding: 8px 16px; }
QMenu::item:selected { background: $suave; color: $sobre_suave; }

QPushButton, QToolButton { border: 1px solid $control; border-radius: 6px; padding: 6px 12px; min-height: 18px;
                           background: $btn_neutro; color: $sobre_primario; font-weight: bold; }
QPushButton:hover, QToolButton:hover { border-color: $foco; background: $btn_neutro_hover; }
QPushButton:focus, QToolButton:focus { border: 2px solid $foco; padding: 5px 11px; }
QPushButton:disabled { background: $superficie2; color: $texto2; border-color: $borde; }
QPushButton#verde, QToolButton#verde { background: $btn_exito; color: #FFFFFF; border-color: $btn_exito; font-weight: bold; }
QPushButton#verde:hover, QToolButton#verde:hover { background: $btn_exito_hover; }
QToolButton::menu-indicator { image: none; }
QPushButton#rojo { background: $btn_peligro; color: #FFFFFF; border-color: $btn_peligro; font-weight: bold; }
QPushButton#rojo:hover { background: $btn_peligro_hover; }
QPushButton#verde:focus, QToolButton#verde:focus, QPushButton#rojo:focus { border: 2px solid $foco; }
QPushButton#verde:disabled, QPushButton#rojo:disabled { background: $superficie2; color: $texto2; border-color: $borde;
                                                        font-weight: normal; }

QFrame#tarjeta { background: $fondo; border: 1px solid $borde; border-radius: 8px; }
QLabel#titulo { font-size: 16px; font-weight: bold; color: $acento; }
QLabel#cifra { font-size: 20px; font-weight: bold; }
QLabel[rol="ayuda"] { font-size: 12px; color: $texto2; }
QLabel[rol="nota"] { color: $texto2; }
QLabel[rol="subtitulo"] { font-weight: bold; color: $texto; }
QLabel[rol="foto"] { border: 1px dashed $control; border-radius: 8px; background: $superficie; color: $texto2; }
QFrame[rol="separador"] { background: $borde; border: none; max-height: 1px; }
QLabel[tono="acento"] { color: $acento; }
QLabel[tono="exito"] { color: $exito; }
QLabel[tono="peligro"] { color: $peligro; }
QLabel[tono="aviso"] { color: $aviso; }
QLabel[tono="neutro"] { color: $texto2; }

QProgressBar { border: 1px solid $borde; border-radius: 6px; background: $superficie; color: $texto; text-align: center; }
QProgressBar::chunk { border-radius: 5px; background: $barra_exito; }
QProgressBar[tono="aviso"]::chunk { background: $barra_aviso; }
QProgressBar[tono="peligro"]::chunk { background: $barra_peligro; }

QSplitter::handle { background: transparent; }
QStatusBar { color: $texto2; }
QScrollBar:vertical { background: transparent; width: 12px; margin: 2px; }
QScrollBar:horizontal { background: transparent; height: 12px; margin: 2px; }
QScrollBar::handle { background: $control; border-radius: 4px; }
QScrollBar::handle:vertical { min-height: 32px; }
QScrollBar::handle:horizontal { min-width: 32px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
""")


def aplicar(codigo: str) -> None:
    """Pone el estilo en toda la app (también en los avisos y ventanas de diálogo)."""
    global _actual
    _actual = codigo if codigo in TEMAS else "claro"
    t = TEMAS[_actual]
    app = QApplication.instance()
    app.setPalette(_paleta(t))
    # sobre las barras va texto: por eso van en un tono mezclado con la superficie
    barras = {f"barra_{n}": mezcla(t[n], t["superficie"], 0.45) for n in ("exito", "aviso", "peligro")}
    qss = _QSS.substitute(t, flecha_abajo=_flecha(f"{_actual}-abajo.png", t["texto2"], False),
                          flecha_arriba=_flecha(f"{_actual}-arriba.png", t["texto2"], True), **barras,
                          **botones_neutros(t))
    if app.styleSheet() != qss:                # reaplicarla obliga a redibujar todas las ventanas
        app.setStyleSheet(qss)
