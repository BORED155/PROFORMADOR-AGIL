"""Pestaña «Costo/gasto proyecto»: control de una proforma contra sus costos y gastos reales (cargados a mano, desde
el XML de la factura electrónica o desde un PDF), con la ganancia o pérdida a medida que se cargan."""

from __future__ import annotations

import datetime as dt
import shutil
from pathlib import Path

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFileDialog,
                               QFormLayout, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QProgressBar, QPushButton, QSplitter, QTableWidgetItem, QVBoxLayout, QWidget)

from .. import comprobantes
from ..informes import fecha_corta
from ..modelo import CATEGORIAS_GASTO, ESTADOS_GASTO, Gasto, nuevo_id, redondear
from .comun import abrir_archivo, dinero, item_texto, numero, spin, tabla

COLUMNAS = [("Fecha", "fecha"), ("Proveedor", "proveedor"), ("RUC", "ruc"), ("Documento", "documento"),
            ("Descripción", "descripcion"), ("Categoría", "categoria"), ("Subtotal", "subtotal"), ("IVA", "iva"),
            ("Total", "total"), ("Estado", "estado"), ("Origen", "origen")]
NUMEROS = {"subtotal", "iva", "total"}


def _numero(texto: str, defecto: float) -> float:
    try:
        return round(float(texto.replace("$", "").replace(" ", "").replace(",", ".")), 2)
    except ValueError:
        return defecto


class DialogoGasto(QDialog):
    """Agregar o revisar un gasto (a mano, o lo leído de un PDF antes de guardarlo)."""

    def __init__(self, g: Gasto, parent=None, titulo="Gasto"):
        super().__init__(parent)
        self.setWindowTitle(titulo)
        self.setMinimumWidth(520)
        self.g = g
        form = QFormLayout(self)
        self.fecha = QDateEdit(calendarPopup=True)
        self.fecha.setDisplayFormat("dd/MM/yyyy")
        self.fecha.setDate(QDate.fromString(g.fecha, "yyyy-MM-dd") if g.fecha else QDate.currentDate())
        self.proveedor = QLineEdit(g.proveedor)
        self.ruc = QLineEdit(g.ruc)
        self.documento = QLineEdit(g.documento)
        self.documento.setPlaceholderText("001-001-000000123")
        self.descripcion = QLineEdit(g.descripcion)
        self.categoria = QComboBox()
        self.categoria.setEditable(True)
        self.categoria.addItems(CATEGORIAS_GASTO)
        self.categoria.setCurrentText(g.categoria)
        self.subtotal, self.iva, self.total = spin(0, 1e8), spin(0, 1e8), spin(0, 1e8)
        self.subtotal.setValue(g.subtotal)
        self.iva.setValue(g.iva)
        self.total.setValue(g.total)
        self.subtotal.valueChanged.connect(self._sumar)
        self.iva.valueChanged.connect(self._sumar)
        self.estado = QComboBox()
        self.estado.addItems(ESTADOS_GASTO)
        self.estado.setCurrentText(g.estado)
        for etiqueta, w in (("Fecha:", self.fecha), ("Proveedor:", self.proveedor), ("RUC:", self.ruc),
                            ("N.º documento:", self.documento), ("Descripción:", self.descripcion),
                            ("Categoría:", self.categoria), ("Subtotal:", self.subtotal), ("IVA:", self.iva),
                            ("Total pagado:", self.total), ("Estado:", self.estado)):
            form.addRow(etiqueta, w)
        if g.origen == "pdf":
            aviso = QLabel("Datos leídos del PDF: revíselos antes de guardar.")
            aviso.setStyleSheet("color: #e65100; font-weight: bold")
            form.addRow("", aviso)
        botones = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        botones.button(QDialogButtonBox.Ok).setText("Guardar")
        botones.button(QDialogButtonBox.Cancel).setText("Cancelar")
        botones.accepted.connect(self.accept)
        botones.rejected.connect(self.reject)
        form.addRow(botones)

    def _sumar(self, *_a) -> None:
        self.total.setValue(round(self.subtotal.value() + self.iva.value(), 2))

    def accept(self) -> None:
        if not self.total.value() and not self.subtotal.value():
            QMessageBox.warning(self, "Falta el valor", "Escriba el valor del gasto.")
            return
        g = self.g
        g.fecha = self.fecha.date().toString("yyyy-MM-dd")
        g.proveedor, g.ruc = self.proveedor.text().strip(), self.ruc.text().strip()
        g.documento, g.descripcion = self.documento.text().strip(), self.descripcion.text().strip()
        g.categoria = self.categoria.currentText().strip().upper() or "OTROS"
        g.subtotal, g.iva = self.subtotal.value(), self.iva.value()
        g.total = self.total.value() or round(g.subtotal + g.iva, 2)
        g.estado = self.estado.currentText()
        super().accept()


class PestanaCostos(QWidget):
    def __init__(self, ventana):
        super().__init__()
        self.v = ventana
        self.datos = ventana.datos
        self._cargando = False

        self.proforma = QComboBox()
        self.proforma.setMinimumWidth(460)
        self.proforma.currentIndexChanged.connect(lambda _i: self.refrescar_gastos())
        sel = QHBoxLayout()
        t = QLabel("Proforma:")
        t.setObjectName("titulo")
        sel.addWidget(t)
        sel.addWidget(self.proforma, 1)
        nota = QLabel("Solo aparecen las proformas guardadas.")
        nota.setStyleSheet("color: #546e7a")
        sel.addWidget(nota)

        # --- tarjetas de control ---
        tarjeta = QFrame()
        tarjeta.setObjectName("tarjeta")
        g = QGridLayout(tarjeta)
        g.setContentsMargins(14, 8, 14, 8)
        self.cifras = {}
        for col, (clave, texto, color) in enumerate((
                ("contrato", "Contrato (paga el cliente)", "#0d47a1"),
                ("presupuesto", "Costo presupuestado", "#37474f"),
                ("gastado", "Gastado hasta hoy", "#c62828"),
                ("pendiente", "Por pagar (pendiente)", "#e65100"),
                ("resultado", "Ganancia / pérdida", "#2e7d32"))):
            lt = QLabel(texto)
            lt.setAlignment(Qt.AlignCenter)
            lc = QLabel()
            lc.setObjectName("cifra")
            lc.setAlignment(Qt.AlignCenter)
            lc.setStyleSheet(f"color: {color}")
            g.addWidget(lt, 0, col)
            g.addWidget(lc, 1, col)
            self.cifras[clave] = lc
        self.barra = QProgressBar()
        self.barra.setTextVisible(True)
        self.barra.setMaximumHeight(18)
        g.addWidget(self.barra, 2, 0, 1, 5)
        self.lbl_estado = QLabel()
        self.lbl_estado.setAlignment(Qt.AlignCenter)
        self.lbl_estado.setStyleSheet("font-weight: bold")
        g.addWidget(self.lbl_estado, 3, 0, 1, 5)

        # --- tabla de gastos ---
        self.t = tabla([c for c, _a in COLUMNAS])
        self.t.horizontalHeader().setSectionResizeMode(0, self.t.horizontalHeader().ResizeMode.ResizeToContents)
        self.t.horizontalHeader().setSectionResizeMode(4, self.t.horizontalHeader().ResizeMode.Stretch)
        self.t.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed |
                               QAbstractItemView.AnyKeyPressed)
        self.t.itemChanged.connect(self._editado)
        self.t.doubleClicked.connect(self._doble_clic)
        b_manual = QPushButton("＋ Gasto manual")
        b_manual.setObjectName("verde")
        b_manual.clicked.connect(self.agregar_manual)
        b_xml = QPushButton("Cargar factura XML…")
        b_xml.setObjectName("azul")
        b_xml.clicked.connect(self.cargar_xml)
        b_pdf = QPushButton("Cargar PDF…")
        b_pdf.setObjectName("azul")
        b_pdf.clicked.connect(self.cargar_pdf)
        b_abrir = QPushButton("Ver comprobante")
        b_abrir.clicked.connect(self.ver_comprobante)
        b_borrar = QPushButton("Eliminar")
        b_borrar.setObjectName("rojo")
        b_borrar.clicked.connect(self.eliminar)
        botones = QHBoxLayout()
        for b in (b_manual, b_xml, b_pdf, b_abrir):
            botones.addWidget(b)
        botones.addStretch(1)
        botones.addWidget(b_borrar)

        # --- resumen por categoría ---
        self.t_cat = tabla(["Categoría", "Gastado", "% del total"])
        self.t_cat.setEditTriggers(QAbstractItemView.NoEditTriggers)

        izq = QWidget()
        li = QVBoxLayout(izq)
        li.setContentsMargins(0, 0, 0, 0)
        tg = QLabel("Costos y gastos cargados (doble clic para editar)")
        tg.setObjectName("titulo")
        li.addWidget(tg)
        li.addWidget(self.t, 1)
        li.addLayout(botones)
        der = QWidget()
        ld = QVBoxLayout(der)
        ld.setContentsMargins(0, 0, 0, 0)
        tc = QLabel("Por categoría")
        tc.setObjectName("titulo")
        ld.addWidget(tc)
        ld.addWidget(self.t_cat, 1)
        div = QSplitter()
        div.addWidget(izq)
        div.addWidget(der)
        div.setSizes([980, 300])

        lay = QVBoxLayout(self)
        lay.addLayout(sel)
        lay.addWidget(tarjeta)
        lay.addWidget(div, 1)
        self.refrescar()

    # --- proforma elegida ---------------------------------------------------------------------
    def actual(self):
        return self.datos.proforma(self.proforma.currentData() or "")

    def refrescar(self, elegir: str | None = None) -> None:
        actual = elegir or self.proforma.currentData()
        self.proforma.blockSignals(True)
        self.proforma.clear()
        for p in sorted(self.datos.proformas, key=lambda p: p.numero, reverse=True):
            c = self.datos.cliente(p.cliente_id)
            partes = [f"N.º {p.numero:04d}", fecha_corta(p.fecha), c.nombre if c else "", p.titulo]
            self.proforma.addItem("  ·  ".join(x for x in partes if x), p.id)
        self.proforma.setCurrentIndex(max(0, self.proforma.findData(actual)))
        self.proforma.blockSignals(False)
        self.refrescar_gastos()

    def gastos(self) -> list[Gasto]:
        p = self.actual()
        return sorted(self.datos.gastos_de(p.id), key=lambda g: (g.fecha, g.proveedor)) if p else []

    def refrescar_gastos(self) -> None:
        p = self.actual()
        gs = self.gastos()
        self._cargando = True
        self.t.setRowCount(len(gs))
        for f, g in enumerate(gs):
            for c, (_t, a) in enumerate(COLUMNAS):
                if a == "fecha":
                    texto, editable = fecha_corta(g.fecha), False
                elif a in NUMEROS:
                    texto, editable = dinero(getattr(g, a)), True
                elif a == "origen":
                    texto = {"xml": "XML", "pdf": "PDF"}.get(g.origen, "Manual") + (" 📎" if g.archivo else "")
                    editable = False
                elif a in ("categoria", "estado"):
                    texto, editable = getattr(g, a), False
                else:
                    texto, editable = getattr(g, a), True
                it = item_texto(texto, editable, a in NUMEROS)
                it.setData(Qt.UserRole, g.id)
                if a == "estado" and g.estado == "PENDIENTE":
                    it.setForeground(QBrush(QColor("#e65100")))
                self.t.setItem(f, c, it)
        self._cargando = False

        # cifras de control
        contrato = p.total() if p else 0.0
        presupuesto = p.costo_total() if p else 0.0
        gastado = redondear(sum(g.total for g in gs))
        pendiente = redondear(sum(g.total for g in gs if g.estado == "PENDIENTE"))
        resultado = redondear(contrato - gastado)
        self.cifras["contrato"].setText(dinero(contrato))
        self.cifras["presupuesto"].setText(dinero(presupuesto))
        self.cifras["gastado"].setText(dinero(gastado))
        self.cifras["pendiente"].setText(dinero(pendiente))
        r = self.cifras["resultado"]
        r.setText(dinero(resultado))
        r.setStyleSheet(f"color: {'#2e7d32' if resultado >= 0 else '#c62828'}")
        usado = gastado / presupuesto * 100 if presupuesto else 0
        self.barra.setMaximum(100)
        self.barra.setValue(int(min(usado, 100)))
        self.barra.setFormat(f"{usado:.2f} % del costo presupuestado".replace(".", ","))
        self.barra.setStyleSheet("QProgressBar::chunk { background: %s; border-radius: 4px; }"
                                 % ("#c62828" if usado > 100 else "#e65100" if usado > 90 else "#2e7d32"))
        if not p:
            self.lbl_estado.setText("Guarde una proforma para poder controlar sus gastos.")
            self.lbl_estado.setStyleSheet("font-weight: bold; color: #546e7a")
        elif resultado < 0:
            self.lbl_estado.setText(f"PÉRDIDA: los gastos superan lo que paga el cliente en {dinero(-resultado)}.")
            self.lbl_estado.setStyleSheet("font-weight: bold; color: #c62828")
        else:
            margen = resultado / contrato * 100 if contrato else 0
            extra = (f"  ·  Se pasó del costo presupuestado en {dinero(gastado - presupuesto)}"
                     if gastado > presupuesto else
                     f"  ·  Quedan {dinero(presupuesto - gastado)} del costo presupuestado")
            self.lbl_estado.setText(f"GANANCIA hasta ahora: {dinero(resultado)} ({numero(margen)} % del contrato){extra}")
            self.lbl_estado.setStyleSheet("font-weight: bold; color: %s" %
                                          ("#e65100" if gastado > presupuesto else "#2e7d32"))

        por_cat: dict[str, float] = {}
        for g in gs:
            por_cat[g.categoria] = por_cat.get(g.categoria, 0) + g.total
        filas = sorted(por_cat.items(), key=lambda x: -x[1])
        self.t_cat.setRowCount(len(filas))
        for f, (cat, val) in enumerate(filas):
            for c, texto in enumerate([cat, dinero(val), f"{numero(val / gastado * 100)} %" if gastado else ""]):
                self.t_cat.setItem(f, c, item_texto(texto, alinear_derecha=c >= 1))

    # --- editar en la tabla -------------------------------------------------------------------
    def _gasto_de_fila(self, fila: int) -> Gasto | None:
        it = self.t.item(fila, 0)
        gid = it.data(Qt.UserRole) if it else None
        return next((g for g in self.datos.gastos if g.id == gid), None)

    def _editado(self, it: QTableWidgetItem) -> None:
        if self._cargando:
            return
        g = self._gasto_de_fila(it.row())
        if g is None:
            return
        a = COLUMNAS[it.column()][1]
        if a in NUMEROS:
            setattr(g, a, max(0.0, _numero(it.text(), getattr(g, a))))
            if a in ("subtotal", "iva"):
                g.total = redondear(g.subtotal + g.iva)
        else:
            setattr(g, a, it.text().strip())
        self.datos.guardar()
        self.refrescar_gastos()

    def _doble_clic(self, indice) -> None:
        a = COLUMNAS[indice.column()][1]
        if a in ("fecha", "categoria", "estado", "origen"):      # estas se cambian en la ventana
            g = self._gasto_de_fila(indice.row())
            if g and DialogoGasto(g, self, "Editar gasto").exec() == QDialog.Accepted:
                self.datos.guardar()
                self.refrescar_gastos()

    # --- cargar -------------------------------------------------------------------------------
    def _proforma_o_aviso(self):
        p = self.actual()
        if p is None:
            QMessageBox.information(self, "Sin proforma", "Primero guarde una proforma y elíjala arriba.")
        return p

    def agregar_manual(self) -> None:
        p = self._proforma_o_aviso()
        if p is None:
            return
        g = Gasto(id=nuevo_id(), proforma_id=p.id, fecha=dt.date.today().isoformat())
        if DialogoGasto(g, self, "Nuevo gasto").exec() == QDialog.Accepted:
            self.datos.gastos.append(g)
            self.datos.guardar()
            self.refrescar_gastos()

    def _guardar_archivo(self, g: Gasto, ruta: Path) -> None:
        destino = self.datos.comprobantes / f"{g.id}{ruta.suffix.lower()}"
        shutil.copy2(ruta, destino)
        g.archivo = destino.name

    def _repetido(self, ruc: str, documento: str) -> str:
        """Si esa factura ya está cargada, dice en qué proforma."""
        if not documento:
            return ""
        for g in self.datos.gastos:
            if g.documento == documento and g.ruc == ruc:
                p = self.datos.proforma(g.proforma_id)
                return f"N.º {p.numero:04d}" if p else "otra proforma"
        return ""

    def _inicio(self) -> str:
        d = Path.home() / "Descargas"
        return str(d if d.is_dir() else Path.home())

    def cargar_xml(self) -> None:
        p = self._proforma_o_aviso()
        if p is None:
            return
        rutas, _ = QFileDialog.getOpenFileNames(self, "Facturas electrónicas (XML)", self._inicio(), "XML (*.xml)")
        agregados, avisos = 0, []
        for r in rutas:
            ruta = Path(r)
            try:
                d = comprobantes.leer_xml(ruta)
            except Exception as e:  # noqa: BLE001 - se informa al usuario
                avisos.append(f"{ruta.name}: {e}")
                continue
            donde = self._repetido(d["ruc"], d["documento"])
            if donde:
                avisos.append(f"{ruta.name}: la factura {d['documento']} ya está cargada en la proforma {donde}.")
                continue
            g = Gasto(id=nuevo_id(), proforma_id=p.id, origen="xml", **d)
            self._guardar_archivo(g, ruta)
            self.datos.gastos.append(g)
            agregados += 1
        if agregados:
            self.datos.guardar()
            self.refrescar_gastos()
        if avisos:
            QMessageBox.warning(self, "Facturas XML", f"Se cargaron {agregados}.\n\n" + "\n".join(avisos))
        elif agregados:
            self.v.statusBar().showMessage(f"Se cargaron {agregados} factura(s) desde XML.", 6000)

    def cargar_pdf(self) -> None:
        p = self._proforma_o_aviso()
        if p is None:
            return
        rutas, _ = QFileDialog.getOpenFileNames(self, "Facturas o comprobantes (PDF)", self._inicio(), "PDF (*.pdf)")
        for r in rutas:
            ruta = Path(r)
            try:
                d = comprobantes.leer_pdf(ruta)
            except Exception as e:  # noqa: BLE001
                QMessageBox.warning(self, "PDF", f"{ruta.name}: {e}\n\nPuede cargarlo como gasto manual.")
                d = {}
            donde = self._repetido(d.get("ruc", ""), d.get("documento", ""))
            if donde and QMessageBox.question(
                    self, "Factura repetida", f"La factura {d['documento']} ya está cargada en la proforma {donde}. "
                                              "¿Cargarla de todos modos?") != QMessageBox.Yes:
                continue
            g = Gasto(id=nuevo_id(), proforma_id=p.id, origen="pdf", **d)
            if DialogoGasto(g, self, f"Revisar: {ruta.name}").exec() == QDialog.Accepted:
                self._guardar_archivo(g, ruta)
                self.datos.gastos.append(g)
                self.datos.guardar()
        self.refrescar_gastos()

    def ver_comprobante(self) -> None:
        g = self._gasto_de_fila(self.t.currentRow())
        if g is None or not g.archivo or not (self.datos.comprobantes / g.archivo).is_file():
            QMessageBox.information(self, "Comprobante", "Ese gasto no tiene un archivo guardado.")
            return
        abrir_archivo(self.datos.comprobantes / g.archivo)

    def eliminar(self) -> None:
        filas = sorted({i.row() for i in self.t.selectedIndexes()})
        gs = [g for g in (self._gasto_de_fila(f) for f in filas) if g]
        if not gs or QMessageBox.question(self, "Eliminar", f"¿Eliminar {len(gs)} gasto(s)?") != QMessageBox.Yes:
            return
        for g in gs:
            if g.archivo:
                (self.datos.comprobantes / g.archivo).unlink(missing_ok=True)
            self.datos.gastos.remove(g)
        self.datos.guardar()
        self.refrescar_gastos()
