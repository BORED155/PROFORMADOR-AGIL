"""Ventana principal del Proformador."""

from __future__ import annotations

import copy
import datetime as dt
import shutil
import subprocess
import unicodedata
from pathlib import Path

from PySide6.QtCore import QDate, QEvent, QModelIndex, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import (QBrush, QColor, QDesktopServices, QFont, QIcon, QKeySequence, QPainter, QPixmap,
                           QShortcut)
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QCompleter, QDateEdit, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFileDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMenu,
                               QMessageBox, QPlainTextEdit, QPushButton, QSizePolicy, QSpinBox, QSplitter, QTableWidget,
                               QTableWidgetItem, QTabWidget, QToolButton, QVBoxLayout, QWidget)

from .. import informes
from .. import paquete
from ..importar import exportar_materiales, importar
from ..modelo import (IVA_OPCIONES, OPCIONALES, TIPO_DISENO, TIPO_INVERSION, TIPO_MATERIAL, Adicional, Cliente, Datos, Empresa, Item, Material,
                      Modulo, Proforma, nuevo_id, redondear, separar_descripcion, unir_descripcion)

ESTILO = """
QMainWindow, QDialog { background: #f5f7f9; }
QTabWidget::pane { border: 1px solid #cfd8dc; border-radius: 12px; background: white; top: -1px; }
QTabBar::tab { background: #eceff1; color: #37474f; border: 1px solid #cfd8dc; padding: 8px 18px; margin-right: 4px;
               border-top-left-radius: 10px; border-top-right-radius: 10px; }
QTabBar::tab:selected { background: white; color: #0d47a1; font-weight: bold; border-bottom-color: white; }
QTableWidget, QListWidget, QPlainTextEdit { border: 1px solid #cfd8dc; border-radius: 10px; background: white;
                                            selection-background-color: #1565c0; selection-color: white; }
QListWidget::item { padding: 5px 4px; }
QHeaderView::section { background: white; border: none; border-bottom: 1px solid #cfd8dc; padding: 6px;
                       font-weight: bold; color: #37474f; }
QLineEdit, QComboBox, QDoubleSpinBox, QSpinBox, QDateEdit { border: 1px solid #cfd8dc; border-radius: 8px;
                                                            padding: 4px 8px; background: white; }
QAbstractSpinBox QLineEdit, QComboBox QLineEdit, QDateEdit QLineEdit { border: none; padding: 0; background: transparent; }
QPushButton { border: 1px solid #cfd8dc; border-radius: 8px; padding: 6px 14px; background: white; }
QPushButton:hover { border-color: #1565c0; }
QPushButton#verde { background: #2e7d32; color: white; border: none; font-weight: bold; }
QPushButton#verde:hover { background: #43a047; }
QPushButton#azul { background: #1565c0; color: white; border: none; font-weight: bold; }
QPushButton#azul:hover { background: #1e88e5; }
QPushButton#rojo { background: #c62828; color: white; border: none; font-weight: bold; }
QPushButton#rojo:hover { background: #e53935; }
QFrame#tarjeta { background: white; border: 1px solid #cfd8dc; border-radius: 12px; }
QLabel#titulo { font-size: 15px; font-weight: bold; color: #0d47a1; }
QLabel#cifra { font-size: 20px; font-weight: bold; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #b0bec5; border-radius: 4px; min-height: 30px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
"""


from .adicionales import PestanaAdicionales
from .comun import (ItemOrdenable, numero, Interruptor, abrir_archivo, pdf_a_imagen, carpeta_proformas, centrado, dinero, item_texto, normalizar,
                    spin, tabla)
from .costos import PestanaCostos


# =============================================================================================
class PestanaProforma(QWidget):
    """Armar la proforma: módulos, adicionales, ganancia y resultado."""

    def __init__(self, ventana: "VentanaPrincipal"):
        super().__init__()
        self.v = ventana
        self.datos = ventana.datos
        self.p: Proforma = self.datos.nueva_proforma()
        self._cargando = False

        # --- buscador de módulos (las recetas se arman en la pestaña Módulos) ---
        self.buscar = QLineEdit()
        self.buscar.setPlaceholderText("🔍  Buscar módulo…  (Ctrl+F)")
        self.buscar.setClearButtonEnabled(True)
        self.buscar.setMinimumHeight(34)
        self.buscar.textChanged.connect(self.filtrar)
        self.buscar.returnPressed.connect(self.agregar_elegido)
        self.buscar.installEventFilter(self)
        QShortcut(QKeySequence("Ctrl+F"), self, activated=self.enfocar_busqueda)
        self.catalogo = QTableWidget(0, 2)
        self.catalogo.setHorizontalHeaderLabels(["Módulo", "Costo"])
        self.catalogo.verticalHeader().setVisible(False)
        self.catalogo.verticalHeader().setDefaultSectionSize(30)
        self.catalogo.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.catalogo.setSelectionMode(QAbstractItemView.SingleSelection)
        self.catalogo.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.catalogo.setShowGrid(False)
        self.catalogo.setWordWrap(False)
        self.catalogo.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.catalogo.horizontalHeader().setSectionResizeMode(1, QHeaderView.Fixed)
        self.catalogo.setColumnWidth(1, 105)
        self.catalogo.cellDoubleClicked.connect(lambda *_a: self.agregar_elegido())
        b_agregar = QPushButton("Agregar a la proforma  ➜")
        b_agregar.setObjectName("azul")
        b_agregar.clicked.connect(self.agregar_elegido)
        caja_cat = QWidget()
        lc = QVBoxLayout(caja_cat)
        lc.setContentsMargins(0, 0, 10, 0)
        t_cat = QLabel("Módulos")
        t_cat.setObjectName("titulo")
        ayuda = QLabel("Escriba para filtrar · ↑↓ para moverse · Enter o doble clic agrega. "
                       "Las recetas se arman en la pestaña «Módulos».")
        ayuda.setWordWrap(True)
        ayuda.setStyleSheet("color: #546e7a; font-size: 11px")
        lc.addWidget(t_cat)
        lc.addWidget(self.buscar)
        lc.addWidget(ayuda)
        lc.addWidget(self.catalogo, 1)
        lc.addWidget(b_agregar)

        # --- datos de la proforma ---
        self.lbl_numero = QLabel()
        self.lbl_numero.setObjectName("titulo")
        self.cliente = QComboBox()
        self.cliente.setMinimumWidth(240)
        self.cliente.currentIndexChanged.connect(self._cambio)
        b_cliente = QPushButton("Nuevo cliente…")
        b_cliente.clicked.connect(self.nuevo_cliente)
        self.titulo = QLineEdit()
        self.titulo.setPlaceholderText("Ej.: Proforma para exhibición de fregaderos - MegaKywi Los Chillos")
        self.titulo.textChanged.connect(self._cambio)
        self.fecha = QDateEdit(calendarPopup=True)
        self.fecha.setDisplayFormat("dd/MM/yyyy")
        self.fecha.dateChanged.connect(self._cambio)
        cab = QGridLayout()
        cab.addWidget(self.lbl_numero, 0, 0)
        cab.addWidget(QLabel("Cliente:"), 0, 1, Qt.AlignRight)
        cab.addWidget(self.cliente, 0, 2)
        cab.addWidget(b_cliente, 0, 3)
        cab.addWidget(QLabel("Fecha:"), 0, 4, Qt.AlignRight)
        cab.addWidget(self.fecha, 0, 5)
        self.empresa = QComboBox()
        self.empresa.setToolTip("Cuál de sus empresas emite esta proforma (se crean en «Datos de mi empresa»)")
        self.empresa.currentIndexChanged.connect(self._cambio)
        cab.addWidget(QLabel("Título:"), 1, 1, Qt.AlignRight)
        cab.addWidget(self.titulo, 1, 2)
        cab.addWidget(QLabel("Empresa:"), 1, 3, Qt.AlignRight)
        cab.addWidget(self.empresa, 1, 4, 1, 2)
        cab.setColumnStretch(2, 1)

        # --- módulos de la proforma ---
        self.t_items = tabla(["Módulo", "Cant.", "Ancho", "Alto", "Prof.", "Costo unit.", "Precio unit.",
                              "Total cliente"])
        self.t_items.setSelectionMode(QAbstractItemView.SingleSelection)
        self.t_items.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed |
                                     QAbstractItemView.AnyKeyPressed)
        self.t_items.itemChanged.connect(self._item_editado)
        b_quitar = QPushButton("Quitar módulo")
        b_quitar.setObjectName("rojo")
        b_quitar.clicked.connect(self.quitar_modulo)
        b_editar = QPushButton("✎  Editar receta en Módulos")
        b_editar.setObjectName("azul")
        b_editar.setToolTip("Abre la pestaña Módulos con este módulo para cambiar su receta")
        b_editar.clicked.connect(self.editar_en_modulos)

        # --- resumen de adicionales (se editan en la pestaña «Adicionales») ---
        self.lbl_adic = QLabel()
        self.lbl_adic.setStyleSheet("color: #37474f")
        self.lbl_adic.setWordWrap(True)
        b_adic = QPushButton("Adicionales…")
        b_adic.setToolTip("Logo, transporte, viáticos… y repartirlos entre los módulos")
        b_adic.clicked.connect(lambda: self.v.pestanas.setCurrentWidget(self.v.pest_adicionales))

        # --- opciones ---
        self.margen = spin(0, 1000, 2, " %")
        self.margen.valueChanged.connect(self._cambio)
        self.iva = QComboBox()
        for codigo, texto, _t in IVA_OPCIONES:
            self.iva.addItem(texto, codigo)
        self.iva.currentIndexChanged.connect(self._cambio)
        self.con_imagenes = QCheckBox("PDF con imágenes")
        self.con_imagenes.setToolTip("Desmarque para que el PDF salga sin las fotos de los módulos ni la imagen "
                                     "del diseño final (el logo sí sale)")
        self.con_imagenes.toggled.connect(self._cambio)
        self.b_imagen = QPushButton("Imagen del diseño final…")
        self.b_imagen.clicked.connect(self.elegir_imagen)
        self.notas = QPlainTextEdit()
        self.notas.setPlaceholderText("Nota para el cliente (opcional, sale en el PDF). Puede escribir varias líneas.")
        self.notas.setFixedHeight(96)
        self.l_cond = QListWidget()
        self.l_cond.setFixedHeight(102)
        self.l_cond.setStyleSheet("QListWidget::item { padding: 3px 4px; } QListWidget { selection-background-color: "
                                  "#e3f2fd; selection-color: #0d47a1; }")
        self.l_cond.setToolTip("Marque la casilla para que la condición salga en esta proforma.\n"
                               "Doble clic (o «Editar») para corregir el texto.")
        self.l_cond.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        self.l_cond.itemChanged.connect(self._condicion_marcada)
        self.nueva_cond = QLineEdit()
        self.nueva_cond.setPlaceholderText("Escriba una condición nueva y presione Enter…")
        self.nueva_cond.returnPressed.connect(self.agregar_condicion)
        b_cond = QPushButton("Agregar")
        b_cond.clicked.connect(self.agregar_condicion)
        b_cond_e = QPushButton("Editar")
        b_cond_e.setToolTip("Corrige el texto de la condición elegida (también con doble clic)")
        b_cond_e.clicked.connect(self.editar_condicion)
        b_cond_q = QPushButton("Quitar")
        b_cond_q.setToolTip("Quita la condición elegida de la lista (para todas las proformas nuevas)")
        b_cond_q.clicked.connect(self.quitar_condicion)
        caja_cond = QWidget()
        lcd = QVBoxLayout(caja_cond)
        lcd.setContentsMargins(0, 0, 0, 0)
        lcd.setSpacing(3)
        tc = QLabel("Condiciones del servicio (marque las que van en esta proforma)")
        tc.setStyleSheet("font-weight: bold; color: #37474f")
        lcd.addWidget(tc)
        lcd.addWidget(self.l_cond)
        fcd = QHBoxLayout()
        fcd.addWidget(self.nueva_cond, 1)
        fcd.addWidget(b_cond)
        fcd.addWidget(b_cond_e)
        fcd.addWidget(b_cond_q)
        lcd.addLayout(fcd)
        self.notas.textChanged.connect(self._cambio)
        opciones = QHBoxLayout()
        opciones.addWidget(QLabel("Ganancia:"))
        opciones.addWidget(self.margen)
        opciones.addSpacing(10)
        opciones.addSpacing(10)
        opciones.addWidget(self.iva)
        opciones.addStretch(1)
        opciones.addWidget(self.con_imagenes)
        opciones.addWidget(self.b_imagen)

        # --- resultado ---
        tarjeta = QFrame()
        tarjeta.setObjectName("tarjeta")
        res = QHBoxLayout(tarjeta)
        res.setContentsMargins(14, 6, 14, 6)
        self.lbl_costo, self.lbl_cliente, self.lbl_ganancia = QLabel(), QLabel(), QLabel()
        for texto, lbl, color in (("Le cuesta a usted:", self.lbl_costo, "#c62828"),
                                  ("Paga el cliente:", self.lbl_cliente, "#0d47a1"),
                                  ("Su ganancia:", self.lbl_ganancia, "#2e7d32")):
            res.addWidget(QLabel(texto))
            lbl.setObjectName("cifra")
            lbl.setStyleSheet(f"color: {color}")
            res.addWidget(lbl)
            lbl.setMinimumWidth(150)          # que el cambio de cifras no mueva lo demás
            res.addSpacing(18)
        res.addStretch(1)
        # resumen en su propia fila, de alto fijo: su largo no cambia el tamaño de nada
        self.lbl_detalle = QLabel()
        self.lbl_detalle.setStyleSheet("color: #546e7a")
        self.lbl_detalle.setWordWrap(False)
        self.lbl_detalle.setFixedHeight(20)
        self.lbl_detalle.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)

        b_nueva = QPushButton("Nueva proforma")
        b_nueva.clicked.connect(self.nueva)
        b_guardar = QPushButton("Guardar")
        b_guardar.clicked.connect(self.guardar)
        b_pdf = QPushButton("📄  PDF para el cliente")
        b_pdf.setObjectName("azul")
        b_pdf.clicked.connect(self.generar_pdf)
        b_excel = QPushButton("📊  Excel de costos (mío)")
        b_excel.setObjectName("verde")
        b_excel.clicked.connect(self.generar_excel)

        der = QWidget()
        ld = QVBoxLayout(der)
        ld.setContentsMargins(0, 0, 0, 0)
        ld.addLayout(cab)
        fila_items = QHBoxLayout()
        lt = QLabel("Módulos de la proforma")
        lt.setObjectName("titulo")
        fila_items.addWidget(lt)
        fila_items.addStretch(1)
        fila_items.addWidget(b_editar)
        fila_items.addWidget(b_quitar)
        bloque_items = QWidget()
        lbi = QVBoxLayout(bloque_items)
        lbi.setContentsMargins(14, 0, 0, 0)
        lbi.addLayout(fila_items)
        lbi.addWidget(self.t_items, 1)
        fila_ad = QHBoxLayout()
        fila_ad.addWidget(self.lbl_adic, 1)
        fila_ad.addWidget(b_adic)
        lbi.addLayout(fila_ad)
        derecha = bloque_items
        centro = QSplitter(Qt.Horizontal)
        centro.addWidget(caja_cat)
        centro.addWidget(derecha)
        centro.setChildrenCollapsible(False)
        centro.setHandleWidth(10)
        centro.setSizes([400, 900])
        ld.addWidget(centro, 1)
        ld.addLayout(opciones)
        fila_notas = QHBoxLayout()
        fila_notas.addWidget(self.notas, 1)
        fila_notas.addWidget(caja_cond, 1)
        ld.addLayout(fila_notas)
        abajo = QHBoxLayout()
        abajo.addWidget(tarjeta, 1)
        col_b = QGridLayout()
        col_b.addWidget(b_nueva, 0, 0)
        col_b.addWidget(b_guardar, 0, 1)
        col_b.addWidget(b_excel, 1, 0)
        col_b.addWidget(b_pdf, 1, 1)
        abajo.addLayout(col_b)
        ld.addWidget(self.lbl_detalle)
        ld.addLayout(abajo)

        lay = QVBoxLayout(self)
        lay.addWidget(der)
        self.refrescar_catalogo()
        self.refrescar_empresas()
        self.mostrar(self.p)
        QTimer.singleShot(0, self.enfocar_busqueda)

    # --- catálogo y clientes ------------------------------------------------------------------
    def refrescar_catalogo(self) -> None:
        self.catalogo.setRowCount(0)
        for m in self.datos.modulos:
            f = self.catalogo.rowCount()
            self.catalogo.insertRow(f)
            for c, texto in enumerate([m.nombre, dinero(self.datos.costo_modulo(m))]):
                it = item_texto(texto, alinear_derecha=(c == 1))
                it.setData(Qt.UserRole, m.id)
                it.setData(Qt.UserRole + 1, normalizar(m.nombre + " " + m.descripcion))
                self.catalogo.setItem(f, c, it)
        self.filtrar()
        self.refrescar_clientes()
        if hasattr(self, "lbl_costo"):
            self.recalcular()

    def modulo_cambiado(self, modulo_id: str) -> None:
        """Se editó un módulo en la pestaña Módulos: la proforma abierta toma su receta nueva."""
        mod = self.datos.modulo(modulo_id)
        if mod is None:
            return
        for n, i in enumerate(self.p.items):
            if i.modulo_id == modulo_id:
                self.p.items[n] = self.datos.item_de(mod, i.cantidad)

    def editar_en_modulos(self) -> None:
        item = self.item_actual()
        if item is None:
            QMessageBox.information(self, "Editar receta", "Elija un módulo de la proforma.")
            return
        if self.datos.modulo(item.modulo_id) is None:      # receta armada antes dentro de la proforma
            self.datos.guardar_como_modulo(item)
        self.v.pest_modulos.refrescar(self.datos.modulos.index(self.datos.modulo(item.modulo_id)))
        self.v.pestanas.setCurrentWidget(self.v.pest_modulos)

    def enfocar_busqueda(self) -> None:
        self.buscar.setFocus()
        self.buscar.selectAll()

    def _dato_fila(self, f: int):
        it = self.catalogo.item(f, 0)
        return it.data(Qt.UserRole) if it else None

    def filtrar(self, *_a) -> None:
        """Deja visibles solo los que contienen todas las palabras escritas, y elige el primero."""
        palabras = normalizar(self.buscar.text()).split()
        titulo_actual, visibles_en_seccion, primero = None, 0, None
        for f in range(self.catalogo.rowCount()):
            if self._dato_fila(f) is None:            # título de sección
                if titulo_actual is not None:
                    self.catalogo.setRowHidden(titulo_actual, visibles_en_seccion == 0)
                titulo_actual, visibles_en_seccion = f, 0
                continue
            ver = all(p in self.catalogo.item(f, 0).data(Qt.UserRole + 1) for p in palabras)
            self.catalogo.setRowHidden(f, not ver)
            if ver:
                visibles_en_seccion += 1
                primero = f if primero is None else primero
        if titulo_actual is not None:
            self.catalogo.setRowHidden(titulo_actual, visibles_en_seccion == 0)
        f = self.catalogo.currentRow()
        if f < 0 or self.catalogo.isRowHidden(f) or self._dato_fila(f) is None:
            if primero is None:
                self.catalogo.clearSelection()
                self.catalogo.setCurrentCell(-1, -1)
            else:
                self.catalogo.setCurrentCell(primero, 0)

    def eventFilter(self, obj, ev) -> bool:
        if obj is self.buscar and ev.type() == QEvent.KeyPress and ev.key() in (Qt.Key_Down, Qt.Key_Up):
            self._mover_eleccion(1 if ev.key() == Qt.Key_Down else -1)
            return True
        return super().eventFilter(obj, ev)

    def _mover_eleccion(self, paso: int) -> None:
        f = self.catalogo.currentRow()
        while 0 <= f + paso < self.catalogo.rowCount():
            f += paso
            if not self.catalogo.isRowHidden(f) and self._dato_fila(f) is not None:
                self.catalogo.setCurrentCell(f, 0)
                return

    def agregar_elegido(self) -> None:
        f = self.catalogo.currentRow()
        if f < 0 or self.catalogo.isRowHidden(f) or self._dato_fila(f) is None:
            return
        mod = self.datos.modulo(self._dato_fila(f))
        if mod:
            self.p.items.append(self.datos.item_de(mod, 1))
            self.recalcular(len(self.p.items) - 1)
            self.enfocar_busqueda()

    def item_actual(self) -> Item | None:
        f = self.t_items.currentRow()
        return self.p.items[f] if 0 <= f < len(self.p.items) else None

    def refrescar_empresas(self) -> None:
        actual = self.p.empresa_id or self.datos.empresa.id
        self.empresa.blockSignals(True)
        self.empresa.clear()
        for e in self.datos.empresas:
            self.empresa.addItem(e.nombre or "(sin nombre)", e.id)
        self.empresa.setCurrentIndex(max(0, self.empresa.findData(actual)))
        self.empresa.blockSignals(False)

    # --- condiciones del servicio ---------------------------------------------------------------
    def _mostrar_condiciones(self) -> None:
        todas = list(self.datos.condiciones) + [c for c in self.p.condiciones if c not in self.datos.condiciones]
        self.l_cond.blockSignals(True)
        self.l_cond.clear()
        for c in todas:
            it = QListWidgetItem(c)
            it.setData(Qt.UserRole, c)                   # texto anterior, para saber qué se editó
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEditable)
            it.setCheckState(Qt.Checked if c in self.p.condiciones else Qt.Unchecked)
            self.l_cond.addItem(it)
        self.l_cond.blockSignals(False)

    def _condicion_marcada(self, it: QListWidgetItem | None = None) -> None:
        if it is not None and it.text() != it.data(Qt.UserRole):
            self._condicion_editada(it)
            return
        self.p.condiciones = [self.l_cond.item(f).text() for f in range(self.l_cond.count())
                              if self.l_cond.item(f).checkState() == Qt.Checked]

    def editar_condicion(self) -> None:
        it = self.l_cond.currentItem()
        if it is None:
            self.v.statusBar().showMessage("Elija primero la condición que quiere corregir.", 4000)
            return
        self.l_cond.editItem(it)

    def _condicion_editada(self, it: QListWidgetItem) -> None:
        """Cambia el texto de una condición en la lista (para las proformas nuevas) y en esta proforma."""
        viejo = it.data(Qt.UserRole)
        nuevo = " ".join(it.text().split()).upper()
        otras = [self.l_cond.item(f).data(Qt.UserRole) for f in range(self.l_cond.count())
                 if self.l_cond.item(f) is not it]
        if nuevo and nuevo != viejo and nuevo not in otras:
            if viejo in self.datos.condiciones:
                self.datos.condiciones[self.datos.condiciones.index(viejo)] = nuevo
                self.datos.guardar()
            self.p.condiciones = [nuevo if c == viejo else c for c in self.p.condiciones]
        elif nuevo in otras:
            self.v.statusBar().showMessage("Esa condición ya está en la lista.", 4000)
        fila = self.l_cond.row(it)
        QTimer.singleShot(0, lambda: (self._mostrar_condiciones(), self.l_cond.setCurrentRow(fila)))

    def agregar_condicion(self) -> None:
        texto = " ".join(self.nueva_cond.text().split()).upper()
        if not texto:
            return
        if texto not in self.datos.condiciones:
            self.datos.condiciones.append(texto)
            self.datos.guardar()
        if texto not in self.p.condiciones:
            self.p.condiciones.append(texto)
        self.nueva_cond.clear()
        self._mostrar_condiciones()

    def quitar_condicion(self) -> None:
        it = self.l_cond.currentItem()
        if it is None:
            return
        texto = it.text()
        if texto in self.datos.condiciones:
            self.datos.condiciones.remove(texto)
            self.datos.guardar()
        if texto in self.p.condiciones:
            self.p.condiciones.remove(texto)
        self._mostrar_condiciones()

    def refrescar_clientes(self) -> None:
        actual = self.cliente.currentData() or self.p.cliente_id
        self.cliente.blockSignals(True)
        self.cliente.clear()
        self.cliente.addItem("— Elija el cliente —", "")
        for c in sorted(self.datos.clientes, key=lambda c: c.nombre.lower()):
            self.cliente.addItem(c.nombre, c.id)
        self.cliente.setCurrentIndex(max(0, self.cliente.findData(actual)))
        self.cliente.blockSignals(False)

    def nuevo_cliente(self) -> None:
        dlg = DialogoCliente(Cliente(id=nuevo_id(), nombre=""), self)
        if dlg.exec() == QDialog.Accepted:
            c = dlg.cliente()
            self.datos.clientes.append(c)
            self.datos.guardar()
            self.v.pest_clientes.refrescar()
            self.refrescar_clientes()
            self.cliente.setCurrentIndex(self.cliente.findData(c.id))

    # --- mostrar / leer la proforma -------------------------------------------------------------
    def mostrar(self, p: Proforma) -> None:
        self._cargando = True
        self.p = p
        self.lbl_numero.setText(f"Proforma N.º {p.numero:04d}")
        self.refrescar_clientes()
        self.cliente.setCurrentIndex(max(0, self.cliente.findData(p.cliente_id)))
        self.titulo.setText(p.titulo)
        self.fecha.setDate(QDate.fromString(p.fecha, "yyyy-MM-dd"))
        self.margen.setValue(p.margen)
        self.iva.setCurrentIndex(max(0, self.iva.findData(p.iva)))
        if self.notas.toPlainText() != p.notas:
            self.notas.setPlainText(p.notas)
        self.b_imagen.setText("Imagen del diseño final ✓" if p.imagen else "Imagen del diseño final…")
        self.con_imagenes.setChecked(p.con_imagenes)
        self.refrescar_empresas()
        self._mostrar_condiciones()
        self._cargando = False
        self.recalcular()

    def _cambio(self, *_a) -> None:
        if self._cargando:
            return
        p = self.p
        p.cliente_id = self.cliente.currentData() or ""
        p.titulo = self.titulo.text()
        p.fecha = self.fecha.date().toString("yyyy-MM-dd")
        p.margen = self.margen.value()
        p.iva = self.iva.currentData()
        p.notas = self.notas.toPlainText()
        p.con_imagenes = self.con_imagenes.isChecked()
        p.empresa_id = self.empresa.currentData() or p.empresa_id
        self.recalcular()

    def recalcular(self, fila: int | None = None) -> None:
        p = self.p
        fila = self.t_items.currentRow() if fila is None else fila
        self._cargando = True
        self.t_items.setRowCount(len(p.items))
        for f, i in enumerate(p.items):
            cu = i.costo_unitario(p.no_cobrar)
            pu = p.precio_unitario(i)
            valores = [(i.nombre, True), (numero(i.cantidad), True), (numero(i.ancho), True), (numero(i.alto), True),
                       (numero(i.prof), True), (dinero(cu), False), (dinero(pu), False),
                       (dinero(redondear(pu * i.cantidad)), False)]
            for c, (texto, editable) in enumerate(valores):
                self.t_items.setItem(f, c, item_texto(texto, editable, c >= 1))
        aparte = sum(p.precio_adicional(a) * a.cantidad for a in p.adicionales_aparte())
        repartido = p.total_distribuido()
        if p.adicionales:
            self.lbl_adic.setText(f"Adicionales: {len(p.adicionales)}  ·  aparte {dinero(aparte)}  ·  repartido en los "
                                  f"módulos {dinero(repartido)}  (precio al cliente)")
        else:
            self.lbl_adic.setText("Sin adicionales (logo, transporte, viáticos…).")
        if p.items:
            fila = min(max(fila, 0), len(p.items) - 1)
            if self.t_items.currentRow() != fila:
                self.t_items.setCurrentCell(fila, 0)
        self._cargando = False
        iva = f" + {p.texto_iva()}: {dinero(p.iva_valor())}" if p.tasa_iva() else ""
        self.lbl_costo.setText(dinero(p.costo_total()))
        self.lbl_cliente.setText(dinero(p.total()))
        self.lbl_ganancia.setText(dinero(p.ganancia()))
        porcentaje = p.ganancia() / p.subtotal() * 100 if p.subtotal() else 0
        viejo = (" · proforma antigua: no cobra " + " ni ".join(n for t, n in OPCIONALES if t in p.no_cobrar)
                 if p.no_cobrar else "")
        if not p.items:
            texto = "Agregue módulos desde el buscador de la izquierda."
        else:
            texto = (f"{numero(p.numero_modulos())} módulo(s) · {numero(p.m2_total())} m² · ganancia del {numero(p.margen)} % sobre el "
                     f"costo ({numero(porcentaje)} % del precio){iva}{viejo}")
        self.lbl_detalle.setText(texto)
        self.lbl_detalle.setToolTip(texto)

    @staticmethod
    def _numero(texto: str, defecto: float) -> float:
        try:
            return float(texto.replace("$", "").replace(" ", "").replace(",", "."))
        except ValueError:
            return defecto

    def _item_editado(self, it: QTableWidgetItem) -> None:
        if self._cargando:
            return
        i = self.p.items[it.row()]
        if it.column() == 0:
            i.nombre = it.text()
        campo = {1: "cantidad", 2: "ancho", 3: "alto", 4: "prof"}.get(it.column())
        if campo:
            setattr(i, campo, max(0.0, self._numero(it.text(), getattr(i, campo))))
        QTimer.singleShot(0, self.recalcular)

    # --- acciones ---------------------------------------------------------------------------

    def quitar_modulo(self) -> None:
        filas = sorted({i.row() for i in self.t_items.selectedIndexes()}, reverse=True)
        if not filas and self.item_actual() is not None:
            filas = [self.t_items.currentRow()]
        for f in filas:
            del self.p.items[f]
        self.recalcular()

    def elegir_imagen(self) -> None:
        ruta, _ = QFileDialog.getOpenFileName(self, "Imagen del diseño final", str(Path.home()),
                                              "Imágenes (*.png *.jpg *.jpeg *.webp)")
        if not ruta:
            if self.p.imagen and QMessageBox.question(self, "Imagen", "¿Quitar la imagen del diseño final?") \
                    == QMessageBox.Yes:
                self.p.imagen = ""
                self.mostrar(self.p)
            return
        destino = self.datos.fotos / f"final-{self.p.id}{Path(ruta).suffix.lower()}"
        shutil.copy2(ruta, destino)
        self.p.imagen = destino.name
        self.mostrar(self.p)

    def nueva(self) -> None:
        self.mostrar(self.datos.nueva_proforma())

    def _validar(self) -> bool:
        if not self.p.items and not self.p.adicionales:
            QMessageBox.information(self, "Proforma vacía", "Agregue al menos un módulo.")
            return False
        if not self.p.cliente_id:
            r = QMessageBox.question(self, "Sin cliente", "La proforma no tiene cliente. ¿Continuar de todos modos?")
            return r == QMessageBox.Yes
        return True

    def guardar(self, silencioso: bool = False) -> None:
        self._cambio()
        self.datos.guardar_proforma(self.p)
        self.v.pest_historial.refrescar()
        if not silencioso:
            self.v.statusBar().showMessage(f"Proforma N.º {self.p.numero:04d} guardada.", 5000)

    def _generar(self, sufijo: str, extension: str, filtro: str, funcion) -> None:
        if not self._validar():
            return
        self.guardar(silencioso=True)
        carpeta = carpeta_proformas()
        carpeta.mkdir(parents=True, exist_ok=True)
        nombre = informes.nombre_archivo(self.p, self.datos, sufijo, extension)
        ruta, _ = QFileDialog.getSaveFileName(self, "Guardar", str(carpeta / nombre), filtro)
        if not ruta:
            return
        ruta = Path(ruta)
        if ruta.suffix.lower() != extension:
            ruta = ruta.with_suffix(extension)
        try:
            funcion(self.p, self.datos, ruta)
        except PermissionError:
            QMessageBox.warning(self, "No se pudo guardar", f"No se pudo escribir {ruta.name}. ¿Está abierto en "
                                                            "otro programa? Ciérrelo e intente de nuevo.")
            return
        abrir_archivo(ruta)
        self.v.statusBar().showMessage(f"Guardado: {ruta}", 8000)

    def generar_pdf(self) -> None:
        self._generar("Cliente", ".pdf", "PDF (*.pdf)", informes.pdf_cliente)

    def generar_excel(self) -> None:
        self._generar("Costos", ".xlsx", "Excel (*.xlsx)", informes.excel_costos)


# =============================================================================================
class PestanaHistorial(QWidget):
    def __init__(self, ventana: "VentanaPrincipal"):
        super().__init__()
        self.v = ventana
        self.datos = ventana.datos
        self.t = tabla(["N.º", "Fecha", "Título", "Cliente", "Le cuesta", "Paga el cliente", "Ganancia"])
        cab = self.t.horizontalHeader()
        cab.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        cab.setSectionResizeMode(2, QHeaderView.Stretch)
        self.t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.t.doubleClicked.connect(lambda _i: self.abrir())
        b_abrir = QPushButton("Abrir")
        b_abrir.setObjectName("azul")
        b_abrir.clicked.connect(self.abrir)
        b_dup = QPushButton("Duplicar con precios actuales")
        b_dup.clicked.connect(self.duplicar)
        b_borrar = QPushButton("Eliminar")
        b_borrar.setObjectName("rojo")
        b_borrar.clicked.connect(self.eliminar)
        b_exp = QPushButton("Exportar historial…")
        b_exp.setToolTip("Guarda todas las proformas (con clientes, gastos, fotos y comprobantes) en un archivo "
                         ".zip para llevarlas a otra PC")
        b_exp.clicked.connect(lambda: self.v.exportar_paquete("historial"))
        b_imp = QPushButton("Importar historial…")
        b_imp.setToolTip("Agrega las proformas de un archivo .zip exportado desde otra PC")
        b_imp.clicked.connect(lambda: self.v.importar_paquete("historial"))
        fila = QHBoxLayout()
        fila.addWidget(b_abrir)
        fila.addWidget(b_dup)
        fila.addStretch(1)
        fila.addWidget(b_exp)
        fila.addWidget(b_imp)
        fila.addWidget(b_borrar)
        lay = QVBoxLayout(self)
        lay.addWidget(self.t)
        lay.addLayout(fila)
        self.refrescar()

    def lista(self) -> list[Proforma]:
        return sorted(self.datos.proformas, key=lambda p: p.numero, reverse=True)

    def refrescar(self) -> None:
        ps = self.lista()
        self.t.setRowCount(len(ps))
        for f, p in enumerate(ps):
            c = self.datos.cliente(p.cliente_id)
            for col, texto in enumerate([f"{p.numero:04d}", informes.fecha_corta(p.fecha), p.titulo or "(sin título)",
                                         c.nombre if c else "", dinero(p.costo_total()), dinero(p.total()),
                                         dinero(p.ganancia())]):
                self.t.setItem(f, col, item_texto(texto, alinear_derecha=col >= 4))

    def _elegida(self) -> Proforma | None:
        f = self.t.currentRow()
        ps = self.lista()
        return ps[f] if 0 <= f < len(ps) else None

    def abrir(self) -> None:
        p = self._elegida()
        if p:
            self.v.pest_proforma.mostrar(copy.deepcopy(p))
            self.v.pestanas.setCurrentWidget(self.v.pest_proforma)

    def duplicar(self) -> None:
        p = self._elegida()
        if not p:
            return
        nueva = copy.deepcopy(p)
        base = self.datos.nueva_proforma()
        nueva.id, nueva.numero, nueva.fecha, nueva.imagen = base.id, base.numero, base.fecha, ""
        nueva.no_cobrar = []
        self.datos.actualizar_precios(nueva)
        self.v.pest_proforma.mostrar(nueva)
        self.v.pestanas.setCurrentWidget(self.v.pest_proforma)
        self.v.statusBar().showMessage("Copia creada con los precios actuales de los materiales. Guárdela si "
                                       "la quiere conservar.", 8000)

    def eliminar(self) -> None:
        p = self._elegida()
        gastos = self.datos.gastos_de(p.id) if p else []
        aviso = f"\n\nTambién se borrarán sus {len(gastos)} gasto(s) cargados." if gastos else ""
        if p and QMessageBox.question(self, "Eliminar", f"¿Eliminar la proforma N.º {p.numero:04d}?{aviso}") \
                == QMessageBox.Yes:
            self.datos.proformas = [x for x in self.datos.proformas if x.id != p.id]
            self.datos.gastos = [g for g in self.datos.gastos if g.proforma_id != p.id]
            self.datos.guardar()
            self.refrescar()


# =============================================================================================
class PestanaModulos(QWidget):
    """Editar los módulos: descripción, medidas, foto y receta (materiales por módulo)."""

    def __init__(self, ventana: "VentanaPrincipal"):
        super().__init__()
        self.v = ventana
        self.datos = ventana.datos
        self._cargando = False
        self.lista = QListWidget()
        self.lista.currentRowChanged.connect(self.mostrar)
        b_nuevo = QPushButton("Nuevo módulo")
        b_nuevo.clicked.connect(self.nuevo)
        b_dup = QPushButton("Duplicar")
        b_dup.clicked.connect(self.duplicar)
        b_borrar = QPushButton("Eliminar")
        b_borrar.setObjectName("rojo")
        b_borrar.clicked.connect(self.eliminar)
        izq = QWidget()
        li = QVBoxLayout(izq)
        li.setContentsMargins(0, 0, 0, 0)
        li.addWidget(self.lista, 1)
        fb = QHBoxLayout()
        fb.addWidget(b_nuevo)
        fb.addWidget(b_dup)
        fb.addWidget(b_borrar)
        li.addLayout(fb)
        b_exp = QPushButton("Exportar…")
        b_exp.setToolTip("Guarda todos los módulos (receta, materiales y fotos) en un archivo .zip para llevarlos "
                         "a otra PC")
        b_exp.clicked.connect(lambda: self.v.exportar_paquete("modulos"))
        b_imp = QPushButton("Importar…")
        b_imp.setToolTip("Agrega los módulos de un archivo .zip exportado desde otra PC")
        b_imp.clicked.connect(lambda: self.v.importar_paquete("modulos"))
        fb2 = QHBoxLayout()
        fb2.addWidget(b_exp)
        fb2.addWidget(b_imp)
        li.addLayout(fb2)

        self.nombre = QLineEdit()
        # descripción estándar: tres campos que el cliente verá en la proforma
        self.d_tipo = QLineEdit()
        self.d_tipo.setPlaceholderText("Ej.: Exhibidor de piso para fregaderos")
        self.d_materiales = QLineEdit()
        self.d_materiales.setPlaceholderText("Ej.: MDF 18 mm, acrílico, perfilería de aluminio")
        self.d_caract = QPlainTextEdit()
        self.d_caract.setPlaceholderText("Una característica por línea")
        self.d_caract.setMaximumHeight(110)
        self.descripcion = (self.d_tipo, self.d_materiales, self.d_caract)
        self.ancho, self.alto, self.prof = spin(0, 100, 2, " m"), spin(0, 100, 2, " m"), spin(0, 100, 2, " m")
        self.foto = QLabel()
        self.foto.setFixedSize(150, 150)
        self.foto.setAlignment(Qt.AlignCenter)
        self.foto.setStyleSheet("border: 1px dashed #b0bec5; border-radius: 10px; background: white")
        b_foto = QPushButton("Cambiar foto…")
        b_foto.clicked.connect(self.elegir_foto)
        for w in (self.nombre, self.ancho, self.alto, self.prof):
            (w.textChanged if isinstance(w, QLineEdit) else w.valueChanged).connect(self.guardar)
        for w in self.descripcion:
            w.textChanged.connect(self.guardar)
        form = QFormLayout()
        form.addRow("Nombre:", self.nombre)
        form.addRow("Tipo:", self.d_tipo)
        form.addRow("Materiales de fabricación:", self.d_materiales)
        form.addRow("Característica específica:", self.d_caract)
        medidas = QHBoxLayout()
        for t, w in (("Ancho", self.ancho), ("Alto", self.alto), ("Prof.", self.prof)):
            medidas.addWidget(QLabel(t))
            medidas.addWidget(w)
        form.addRow("Medidas:", medidas)
        cab = QHBoxLayout()
        cab.addLayout(form, 1)
        cf = QVBoxLayout()
        cf.addWidget(self.foto)
        cf.addWidget(b_foto)
        cab.addLayout(cf)

        self.t_receta = tabla(["Material", "Cantidad por módulo", "Unidad", "Precio", "Subtotal"])
        self.t_receta.itemChanged.connect(self._receta_editada)
        # buscador desplegable de materiales: se escribe para filtrar o se abre con la flecha
        self.c_mat = QComboBox()
        self.c_mat.setEditable(True)
        self.c_mat.setInsertPolicy(QComboBox.NoInsert)
        self.c_mat.setMinimumWidth(420)
        self.c_mat.setMaxVisibleItems(18)
        self.c_mat.lineEdit().setPlaceholderText("🔍  Escriba para buscar un material…")
        self.c_mat.lineEdit().setClearButtonEnabled(True)
        self.c_mat.lineEdit().returnPressed.connect(self._agregar_escrito)
        self.c_mat.activated.connect(self._agregar_elegido_combo)
        self.completador = QCompleter(self.c_mat)
        self.completador.setModel(self.c_mat.model())
        self.completador.setCompletionRole(Qt.UserRole + 1)       # nombre sin tildes, en minúsculas
        self.completador.setFilterMode(Qt.MatchContains)
        self.completador.setCaseSensitivity(Qt.CaseInsensitive)
        self.completador.setMaxVisibleItems(18)
        self.completador.activated[QModelIndex].connect(lambda i: self._agregar_elegido_combo(i.row()))
        self.c_mat.setCompleter(self.completador)
        espaciado = "QListView { font-size: 13px; } QListView::item { padding: 6px 8px; }"
        self.completador.popup().setStyleSheet(espaciado)
        self.c_mat.view().setStyleSheet(espaciado)
        b_agregar_mat = QPushButton("Agregar")
        b_agregar_mat.setObjectName("azul")
        b_agregar_mat.clicked.connect(self._agregar_escrito)
        b_quitar = QPushButton("Quitar material")
        b_quitar.clicked.connect(self.quitar_material)
        self.lbl_costo = QLabel()
        self.lbl_costo.setObjectName("titulo")
        fr = QHBoxLayout()
        lr = QLabel("Receta: materiales para UN módulo")
        lr.setObjectName("titulo")
        fr.addWidget(lr)
        fr.addStretch(1)
        fr.addWidget(self.c_mat, 1)
        fr.addWidget(b_agregar_mat)
        fr.addWidget(b_quitar)
        der = QWidget()
        ld = QVBoxLayout(der)
        ld.addLayout(cab)
        ld.addLayout(fr)
        ld.addWidget(self.t_receta, 1)
        ld.addWidget(self.lbl_costo)
        div = QSplitter()
        div.addWidget(izq)
        div.addWidget(der)
        div.setSizes([300, 900])
        lay = QVBoxLayout(self)
        lay.addWidget(div)
        self.refrescar()

    def _avisar(self) -> None:
        """La proforma abierta toma los cambios del módulo y se actualiza el buscador de módulos."""
        m = self.actual()
        if m is not None:
            self.v.pest_proforma.modulo_cambiado(m.id)
        self.v.pest_proforma.refrescar_catalogo()

    def actual(self) -> Modulo | None:
        f = self.lista.currentRow()
        return self.datos.modulos[f] if 0 <= f < len(self.datos.modulos) else None

    def refrescar(self, fila: int | None = None) -> None:
        self._llenar_materiales()
        fila = self.lista.currentRow() if fila is None else fila
        self.lista.blockSignals(True)
        self.lista.clear()
        for m in self.datos.modulos:
            self.lista.addItem(QListWidgetItem(m.nombre))
        self.lista.blockSignals(False)
        self.lista.setCurrentRow(min(max(fila, 0), len(self.datos.modulos) - 1))
        self.mostrar()

    def mostrar(self, *_a) -> None:
        m = self.actual()
        self._cargando = True
        for w in (self.nombre, *self.descripcion, self.ancho, self.alto, self.prof):
            w.setEnabled(m is not None)
        if m is not None:
            self.nombre.setText(m.nombre)
            tipo, materiales, caract = separar_descripcion(m.descripcion)
            self.d_tipo.setText(tipo)
            self.d_materiales.setText(materiales)
            self.d_caract.setPlainText(caract)
            self.ancho.setValue(m.ancho)
            self.alto.setValue(m.alto)
            self.prof.setValue(m.prof)
            foto = self.datos.ruta_foto(m.foto)
            self.foto.setPixmap(QPixmap(str(foto)).scaled(146, 146, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                                if foto else QPixmap())
            self.foto.setText("" if foto else "Sin foto")
        self._mostrar_receta()
        self._cargando = False

    def _mostrar_receta(self) -> None:
        m = self.actual()
        filas = [(self.datos.material(mid), cant) for mid, cant in (m.receta.items() if m else [])]
        filas = [(mat, c) for mat, c in filas if mat is not None]
        cargando = self._cargando
        self._cargando = True
        self.t_receta.setRowCount(len(filas))
        for f, (mat, cant) in enumerate(filas):
            for c, (texto, editable) in enumerate([(mat.nombre, False), (numero(cant), True), (mat.unidad, False),
                                                   (dinero(mat.precio), False), (dinero(cant * mat.precio), False)]):
                it = item_texto(texto, editable, c >= 1)
                it.setData(Qt.UserRole, mat.id)
                self.t_receta.setItem(f, c, it)
        self._cargando = cargando
        if m:
            con = self.datos.costo_modulo(m)
            self.lbl_costo.setText(f"Costo del módulo: {dinero(con)}")

    def guardar(self, *_a) -> None:
        m = self.actual()
        if self._cargando or m is None:
            return
        m.nombre = self.nombre.text()
        m.descripcion = unir_descripcion(self.d_tipo.text(), self.d_materiales.text(), self.d_caract.toPlainText())
        m.ancho, m.alto, m.prof = self.ancho.value(), self.alto.value(), self.prof.value()
        self.lista.currentItem().setText(m.nombre)
        self.datos.guardar()
        self._avisar()

    def _receta_editada(self, it: QTableWidgetItem) -> None:
        m = self.actual()
        if self._cargando or m is None or it.column() != 1:
            return
        try:
            m.receta[it.data(Qt.UserRole)] = max(0.0, float(it.text().replace(",", ".")))
        except ValueError:
            pass
        self.datos.guardar()
        QTimer.singleShot(0, self._tras_cantidad)

    def _tras_cantidad(self) -> None:
        self._mostrar_receta()
        self.c_mat.setFocus()
        self._avisar()

    def _llenar_materiales(self) -> None:
        self.c_mat.blockSignals(True)
        self.c_mat.clear()
        for mat in self.datos.materiales:
            self.c_mat.addItem(f"{mat.nombre}   —   {dinero(mat.precio)} / {mat.unidad}", mat.id)
            self.c_mat.setItemData(self.c_mat.count() - 1, normalizar(mat.nombre), Qt.UserRole + 1)
        self.c_mat.setCurrentIndex(-1)
        self.c_mat.clearEditText()
        self.c_mat.blockSignals(False)

    def _agregar_elegido_combo(self, fila: int) -> None:
        mat = self.datos.material(self.c_mat.itemData(fila)) if fila >= 0 else None
        if mat is not None:
            QTimer.singleShot(0, lambda: self._agregar_material(mat))

    def _agregar_escrito(self) -> None:
        """Enter o botón Agregar: el primer material que contiene todas las palabras escritas."""
        palabras = normalizar(self.c_mat.currentText().split("   —   ")[0]).split()
        if not palabras:
            self.c_mat.showPopup()
            return
        for mat in self.datos.materiales:
            if all(p in normalizar(mat.nombre) for p in palabras):
                QTimer.singleShot(0, lambda mat=mat: self._agregar_material(mat))
                return
        self.v.statusBar().showMessage("No hay ningún material con ese nombre.", 4000)

    def _agregar_material(self, mat: Material) -> None:
        m = self.actual()
        if not m:
            return
        if mat.id not in m.receta:
            m.receta[mat.id] = 1
            self.datos.guardar()
            self._avisar()
        self._mostrar_receta()
        self.c_mat.setCurrentIndex(-1)
        self.c_mat.clearEditText()
        for f in range(self.t_receta.rowCount()):            # cursor en la cantidad de ese material
            if self.t_receta.item(f, 0).data(Qt.UserRole) == mat.id:
                self.t_receta.setCurrentCell(f, 1)
                self.t_receta.setFocus()
                self.t_receta.editItem(self.t_receta.item(f, 1))
                break

    def quitar_material(self) -> None:
        m = self.actual()
        if not m:
            return
        for f in sorted({i.row() for i in self.t_receta.selectedIndexes()}, reverse=True):
            mid = self.t_receta.item(f, 0).data(Qt.UserRole)
            m.receta.pop(mid, None)
        self.datos.guardar()
        self._mostrar_receta()
        self._avisar()

    def elegir_foto(self) -> None:
        m = self.actual()
        if not m:
            return
        ruta, _ = QFileDialog.getOpenFileName(self, "Foto del módulo", str(Path.home()),
                                              "Imágenes (*.png *.jpg *.jpeg *.webp)")
        if ruta:
            destino = self.datos.fotos / f"{m.id}-{nuevo_id()[:4]}{Path(ruta).suffix.lower()}"
            shutil.copy2(ruta, destino)
            m.foto = destino.name
            self.datos.guardar()
            self.refrescar()
            self._avisar()

    def nuevo(self) -> None:
        self.datos.modulos.append(Modulo(id=nuevo_id(), nombre="Módulo nuevo"))
        self.datos.guardar()
        self.refrescar(len(self.datos.modulos) - 1)
        self.nombre.setFocus()
        self.nombre.selectAll()
        self._avisar()

    def duplicar(self) -> None:
        m = self.actual()
        if m:
            copia = copy.deepcopy(m)
            copia.id, copia.nombre = nuevo_id(), m.nombre + " (copia)"
            self.datos.modulos.append(copia)
            self.datos.guardar()
            self.refrescar(len(self.datos.modulos) - 1)
            self._avisar()

    def eliminar(self) -> None:
        m = self.actual()
        if m and QMessageBox.question(self, "Eliminar", f"¿Eliminar el módulo «{m.nombre}»?\n\nLas proformas ya "
                                      "guardadas no cambian.") == QMessageBox.Yes:
            self.datos.modulos.remove(m)
            self.datos.guardar()
            self.refrescar()
            self.v.pest_proforma.refrescar_catalogo()


# =============================================================================================
class PestanaTabla(QWidget):
    """Base para Materiales y Clientes: una tabla editable que se guarda al momento, con buscador (sin tildes) y
    orden alfabético / numérico al hacer clic en un encabezado."""

    columnas: list[tuple[str, str]] = []
    numericas: set[str] = set()          # atributos que se ordenan como número

    def __init__(self, ventana: "VentanaPrincipal", ayuda: str, importar: bool = False):
        super().__init__()
        self.v = ventana
        self.datos = ventana.datos
        self._cargando = False
        self.buscar = QLineEdit()
        self.buscar.setPlaceholderText("🔍  Buscar…  (escriba parte del nombre; no importan tildes ni mayúsculas)")
        self.buscar.setClearButtonEnabled(True)
        self.buscar.textChanged.connect(self.filtrar)
        self.lbl_cuenta = QLabel()
        self.lbl_cuenta.setStyleSheet("color: #546e7a")
        self.t = tabla([c for c, _a in self.columnas])
        self.t.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed |
                               QAbstractItemView.AnyKeyPressed)
        self.t.setSortingEnabled(False)
        cab = self.t.horizontalHeader()
        cab.setSectionsClickable(True)
        cab.setSortIndicatorShown(True)
        cab.setToolTip("Clic en un encabezado para ordenar (otro clic invierte el orden)")
        cab.sectionClicked.connect(self._ordenar)
        self._orden: tuple[int, Qt.SortOrder] | None = None
        self.t.itemChanged.connect(self._editado)
        b_nuevo = QPushButton("Agregar")
        b_nuevo.clicked.connect(self.agregar)
        b_borrar = QPushButton("Eliminar")
        b_borrar.setObjectName("rojo")
        b_borrar.clicked.connect(self.eliminar)
        fila = QHBoxLayout()
        nota = QLabel(ayuda)
        nota.setStyleSheet("color: #546e7a")
        nota.setWordWrap(True)
        fila.addWidget(nota, 1)
        if importar:
            b_imp = QPushButton("Importar desde Excel…")
            b_imp.setObjectName("azul")
            b_imp.setToolTip("Agrega los materiales, módulos y clientes NUEVOS de un Excel con hoja RECETA. "
                             "Lo que ya tiene (mismo nombre) no se modifica.")
            b_imp.clicked.connect(lambda: self.v.importar_excel())
            fila.addWidget(b_imp)
            b_exp = QPushButton("Exportar a Excel…")
            b_exp.setToolTip("Guarda la lista de materiales y precios en un Excel para llevarla a otra máquina "
                             "(allá se carga con «Importar desde Excel…»).")
            b_exp.clicked.connect(lambda: self.v.exportar_materiales_excel())
            fila.addWidget(b_exp)
        fila.addWidget(b_nuevo)
        fila.addWidget(b_borrar)
        arriba = QHBoxLayout()
        arriba.addWidget(self.buscar, 1)
        arriba.addWidget(self.lbl_cuenta)
        lay = QVBoxLayout(self)
        lay.addLayout(arriba)
        lay.addWidget(self.t)
        lay.addLayout(fila)
        self.refrescar()

    def lista(self) -> list:
        raise NotImplementedError

    def refrescar(self) -> None:
        self._cargando = True
        filas = self.lista()
        self.t.setRowCount(len(filas))
        for f, obj in enumerate(filas):
            for c, (_t, atributo) in enumerate(self.columnas):
                self.t.setItem(f, c, self.celda(obj, atributo))
        if self._orden is not None:
            self.t.sortItems(*self._orden)
        self._cargando = False
        self.filtrar()

    def texto(self, obj, atributo) -> str:
        return str(getattr(obj, atributo))

    def celda(self, obj, atributo) -> QTableWidgetItem:
        texto = self.texto(obj, atributo)
        clave = getattr(obj, atributo) if atributo in self.numericas else normalizar(texto)
        it = ItemOrdenable(texto, clave)
        it.setData(Qt.UserRole, obj.id)
        if atributo in self.numericas:
            it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        return it

    def _ordenar(self, columna: int) -> None:
        if self._orden and self._orden[0] == columna and self._orden[1] == Qt.AscendingOrder:
            orden = Qt.DescendingOrder
        else:
            orden = Qt.AscendingOrder
        self._orden = (columna, orden)
        self.t.horizontalHeader().setSortIndicator(columna, orden)
        self._cargando = True
        self.t.sortItems(columna, orden)
        self._cargando = False

    def filtrar(self, *_a) -> None:
        palabras = normalizar(self.buscar.text()).split()
        visibles = 0
        for f in range(self.t.rowCount()):
            texto = " ".join(normalizar(self.t.item(f, c).text()) for c in range(self.t.columnCount())
                             if self.t.item(f, c))
            ver = all(p in texto for p in palabras)
            self.t.setRowHidden(f, not ver)
            visibles += ver
        total = self.t.rowCount()
        self.lbl_cuenta.setText(f"{visibles} de {total}" if palabras else f"{total} en total")

    def objeto(self, fila: int):
        it = self.t.item(fila, 0)
        id_ = it.data(Qt.UserRole) if it else None
        return next((o for o in self.lista() if o.id == id_), None)

    def fila_de(self, obj) -> int:
        for f in range(self.t.rowCount()):
            if self.t.item(f, 0) and self.t.item(f, 0).data(Qt.UserRole) == obj.id:
                return f
        return -1

    def _editado(self, it: QTableWidgetItem) -> None:
        if self._cargando:
            return
        obj = self.objeto(it.row())
        if obj is None:
            return
        atributo = self.columnas[it.column()][1]
        self.asignar(obj, atributo, it)
        self._cargando = True
        it.setText(self.texto(obj, atributo))
        it.clave = getattr(obj, atributo) if atributo in self.numericas else normalizar(it.text())
        self._cargando = False
        self.datos.guardar()
        self.v.pest_proforma.refrescar_catalogo()

    def asignar(self, obj, atributo, it) -> None:
        setattr(obj, atributo, it.text().strip())

    def agregar(self) -> None:
        raise NotImplementedError

    def editar_nuevo(self, obj) -> None:
        """Tras agregar: limpia el buscador y abre el nombre de la fila nueva para escribirlo."""
        self.buscar.clear()
        self.refrescar()
        f = self.fila_de(obj)
        if f >= 0:
            self.t.scrollToItem(self.t.item(f, 0))
            self.t.editItem(self.t.item(f, 0))

    def eliminar(self) -> None:
        objs = [o for o in (self.objeto(f) for f in sorted({i.row() for i in self.t.selectedIndexes()}))
                if o is not None]
        if not objs or QMessageBox.question(self, "Eliminar", f"¿Eliminar {len(objs)} fila(s)?") != QMessageBox.Yes:
            return
        lista = self.lista()
        for o in objs:
            lista.remove(o)
        self.datos.guardar()
        self.refrescar()
        self.v.pest_proforma.refrescar_catalogo()


class PestanaMateriales(PestanaTabla):
    columnas = [("Material", "nombre"), ("Unidad", "unidad"), ("Precio", "precio")]
    numericas = {"precio"}

    def __init__(self, ventana):
        super().__init__(ventana, importar=True, ayuda="Cambie los precios aquí: se usan en las proformas nuevas (las guardadas no "
                                                         "cambian). Diseño, inversión y demás se agregan como materiales.")

    def lista(self):
        return self.datos.materiales

    def texto(self, obj, atributo) -> str:
        return numero(obj.precio) if atributo == "precio" else super().texto(obj, atributo)

    def asignar(self, obj, atributo, it):
        if atributo == "precio":
            try:
                obj.precio = redondear(max(0.0, float(it.text().replace("$", "").replace(" ", "").replace(",", "."))))
            except ValueError:
                pass
        else:
            super().asignar(obj, atributo, it)

    def agregar(self):
        m = Material(id=nuevo_id(), nombre="NUEVO MATERIAL", precio=0)
        self.datos.materiales.append(m)
        self.datos.guardar()
        self.editar_nuevo(m)


class PestanaClientes(PestanaTabla):
    columnas = [("Cliente", "nombre"), ("RUC", "ruc"), ("Dirección", "direccion"), ("Contacto", "contacto"),
                ("Correo", "correo")]

    def __init__(self, ventana):
        super().__init__(ventana, "Los datos del cliente aparecen en la cabecera de su proforma.")

    def lista(self):
        return self.datos.clientes

    def agregar(self):
        c = Cliente(id=nuevo_id(), nombre="NUEVO CLIENTE")
        self.datos.clientes.append(c)
        self.datos.guardar()
        self.editar_nuevo(c)
        self.v.pest_proforma.refrescar_clientes()


class DialogoCliente(QDialog):
    def __init__(self, c: Cliente, parent=None):
        super().__init__(parent)
        self.c = c
        self.setWindowTitle("Cliente")
        self.campos = {}
        form = QFormLayout(self)
        for etiqueta, atributo in PestanaClientes.columnas:
            w = QLineEdit(getattr(c, atributo))
            self.campos[atributo] = w
            form.addRow(etiqueta + ":", w)
        b = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        b.button(QDialogButtonBox.Ok).setText("Guardar")
        b.button(QDialogButtonBox.Cancel).setText("Cancelar")
        b.accepted.connect(self.accept)
        b.rejected.connect(self.reject)
        form.addRow(b)

    def accept(self):
        if not self.campos["nombre"].text().strip():
            self.campos["nombre"].setFocus()
            return
        super().accept()

    def cliente(self) -> Cliente:
        for atributo, w in self.campos.items():
            setattr(self.c, atributo, w.text().strip())
        return self.c


# =============================================================================================
class PestanaEmpresa(QWidget):
    """Mis empresas: datos que salen en la proforma. A la derecha, la lista para elegir una rápido; la elegida es
    la que se usa por defecto en las proformas nuevas."""

    def __init__(self, ventana: "VentanaPrincipal"):
        super().__init__()
        self.v = ventana
        self.datos = ventana.datos
        self._cargando = False
        self.campos = {}
        form = QFormLayout()
        for etiqueta, atributo in (("Nombre o razón social", "nombre"), ("RUC", "ruc"), ("Dirección", "direccion"),
                                   ("Teléfono", "telefono"), ("Correo", "correo")):
            w = QLineEdit()
            w.textChanged.connect(self.guardar)
            self.campos[atributo] = w
            form.addRow(etiqueta + ":", w)
        self.logo = QLabel()
        self.logo.setFixedSize(220, 120)
        self.logo.setAlignment(Qt.AlignCenter)
        self.logo.setStyleSheet("border: 1px dashed #b0bec5; border-radius: 10px; background: white")
        b_logo = QPushButton("Elegir logo…")
        b_logo.clicked.connect(self.elegir_logo)
        fl = QHBoxLayout()
        fl.addWidget(self.logo)
        fl.addWidget(b_logo)
        fl.addStretch(1)
        form.addRow("Logo:", fl)

        # hoja membretada (fondo de cada página del PDF)
        self.membrete = QLabel()
        self.membrete.setFixedSize(85, 120)                 # proporción A4
        self.membrete.setAlignment(Qt.AlignCenter)
        self.membrete.setStyleSheet("border: 1px dashed #b0bec5; border-radius: 6px; background: white; "
                                    "color: #90a4ae; font-size: 10px")
        b_memb = QPushButton("Elegir hoja membretada…")
        b_memb.setToolTip("Imagen (PNG/JPG) o PDF de su hoja membretada, tamaño A4. Va de fondo en cada página.")
        b_memb.clicked.connect(self.elegir_membrete)
        self.b_memb_q = QPushButton("Quitar")
        self.b_memb_q.clicked.connect(self.quitar_membrete)
        self.memb_sup, self.memb_inf = spin(5, 150, 0, " mm"), spin(5, 150, 0, " mm")
        self.memb_sup.setToolTip("Espacio libre arriba para no escribir sobre el encabezado del membrete")
        self.memb_inf.setToolTip("Espacio libre abajo para no escribir sobre el pie del membrete")
        for w in (self.memb_sup, self.memb_inf):
            w.valueChanged.connect(self.guardar)
        cm = QVBoxLayout()
        fbm = QHBoxLayout()
        fbm.addWidget(b_memb)
        fbm.addWidget(self.b_memb_q)
        fbm.addStretch(1)
        cm.addLayout(fbm)
        fes = QHBoxLayout()
        fes.addWidget(QLabel("Espacio arriba:"))
        fes.addWidget(self.memb_sup)
        fes.addWidget(QLabel("abajo:"))
        fes.addWidget(self.memb_inf)
        fes.addStretch(1)
        cm.addLayout(fes)
        am = QLabel("Si tiene hoja membretada, el PDF se imprime sobre ella (sin repetir logo ni datos de la "
                    "empresa). Ajuste los espacios para no tapar el encabezado y el pie.")
        am.setWordWrap(True)
        am.setStyleSheet("color: #546e7a; font-size: 11px")
        cm.addWidget(am)
        fm = QHBoxLayout()
        fm.addWidget(self.membrete, 0, Qt.AlignTop)
        fm.addLayout(cm, 1)

        # marca de agua con el logo (cuando no hay membrete)
        self.marca_agua = QCheckBox("Poner el logo de fondo como marca de agua")
        self.marca_agua.toggled.connect(self.guardar)
        self.intensidad = spin(1, 100, 0, " %")
        self.intensidad.setToolTip("Qué tan visible queda el fondo del PDF: la hoja membretada o el logo como "
                                   "marca de agua (100 % = colores originales; 8 % = muy suave)")
        self.intensidad.valueChanged.connect(self.guardar)
        b_ejemplo = QPushButton("Previsualización")
        b_ejemplo.setObjectName("azul")
        b_ejemplo.setToolTip("Arma un PDF de prueba con esta empresa para ver cómo queda")
        b_ejemplo.clicked.connect(self.ver_ejemplo)
        fma = QHBoxLayout()
        fma.addWidget(self.marca_agua)
        fma.addWidget(QLabel("Intensidad del fondo:"))
        fma.addWidget(self.intensidad)
        fma.addStretch(1)
        fma.addWidget(b_ejemplo)
        self.margen = spin(0, 1000, 2, " %")
        self.margen.valueChanged.connect(self.guardar)
        form.addRow("Ganancia por defecto:", self.margen)
        self.iva = QComboBox()
        for codigo, texto, _t in IVA_OPCIONES:
            self.iva.addItem(texto, codigo)
        self.iva.currentIndexChanged.connect(self.guardar)
        form.addRow("IVA por defecto:", self.iva)
        self.validez = QSpinBox()
        self.validez.setRange(0, 365)
        self.validez.setSuffix(" días")
        self.validez.setSpecialValueText("no mostrar")
        self.validez.valueChanged.connect(self.guardar)
        form.addRow("Validez de la proforma:", self.validez)
        separador = QFrame()                       # aparta la sección de hoja membretada / marca de agua
        separador.setFrameShape(QFrame.HLine)
        separador.setStyleSheet("color: #cfd8dc")
        caja_sep = QWidget()
        lsep = QVBoxLayout(caja_sep)
        lsep.setContentsMargins(0, 14, 0, 10)
        lsep.addWidget(separador)
        form.addRow(caja_sep)
        form.addRow("Hoja membretada:", fm)
        form.addRow("Marca de agua:", fma)
        nota = QLabel("Las condiciones del servicio se eligen en cada proforma; los adicionales rápidos están en la "
                      "pestaña «Adicionales».")
        nota.setWordWrap(True)
        nota.setStyleSheet("color: #546e7a")
        form.addRow("", nota)
        caja = QWidget()
        caja.setMaximumWidth(760)
        caja.setLayout(form)

        # --- lista de mis empresas (a la derecha) ---
        self.lista = QListWidget()
        self.lista.setMinimumWidth(300)
        self.lista.currentRowChanged.connect(self._elegida)
        b_nueva = QPushButton("＋ Nueva empresa")
        b_nueva.setObjectName("verde")
        b_nueva.clicked.connect(self.nueva)
        b_borrar = QPushButton("Eliminar")
        b_borrar.setObjectName("rojo")
        b_borrar.clicked.connect(self.eliminar)
        der = QWidget()
        ld = QVBoxLayout(der)
        ld.setContentsMargins(0, 0, 0, 0)
        t = QLabel("Mis empresas")
        t.setObjectName("titulo")
        ayuda = QLabel("Haga clic en una para ver o cambiar sus datos. La elegida (★) es la que se usa en las "
                       "proformas nuevas.")
        ayuda.setWordWrap(True)
        ayuda.setStyleSheet("color: #546e7a; font-size: 11px")
        ld.addWidget(t)
        ld.addWidget(ayuda)
        ld.addWidget(self.lista, 1)
        fb = QHBoxLayout()
        fb.addWidget(b_nueva)
        fb.addWidget(b_borrar)
        ld.addLayout(fb)

        lay = QHBoxLayout(self)
        lay.addWidget(caja, 1)
        lay.addSpacing(16)
        lay.addWidget(der)
        self.refrescar()

    def refrescar(self) -> None:
        activa = self.datos.empresa
        self.lista.blockSignals(True)
        self.lista.clear()
        for e in self.datos.empresas:
            self.lista.addItem(("★  " if e.id == activa.id else "     ") + (e.nombre or "(sin nombre)"))
        self.lista.setCurrentRow(self.datos.empresas.index(activa))
        self.lista.blockSignals(False)
        self.mostrar()

    def _elegida(self, fila: int) -> None:
        if 0 <= fila < len(self.datos.empresas):
            self.datos.empresa_activa = self.datos.empresas[fila].id
            self.datos.guardar()
            self.refrescar()
            self.v.pest_proforma.refrescar_empresas()

    def mostrar(self) -> None:
        e = self.datos.empresa
        self._cargando = True
        for atributo, w in self.campos.items():
            w.setText(getattr(e, atributo))
        self.margen.setValue(e.margen)
        self.iva.setCurrentIndex(max(0, self.iva.findData(e.iva)))
        self.validez.setValue(e.validez_dias)
        self.memb_sup.setValue(e.membrete_sup)
        self.memb_inf.setValue(e.membrete_inf)
        self.marca_agua.setChecked(e.marca_agua)
        self.intensidad.setValue(e.marca_agua_intensidad)
        self._cargando = False
        self._mostrar_logo()
        self._mostrar_membrete()

    def _mostrar_membrete(self) -> None:
        ruta = self.datos.ruta_foto(self.datos.empresa.membrete)
        self.membrete.setPixmap(QPixmap(str(ruta)).scaled(83, 118, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                                if ruta else QPixmap())
        self.membrete.setText("" if ruta else "Sin\nmembrete")
        self.b_memb_q.setEnabled(bool(ruta))
        for w in (self.memb_sup, self.memb_inf):
            w.setEnabled(bool(ruta))
        self.marca_agua.setEnabled(not ruta)
        self.marca_agua.setToolTip("Con hoja membretada no se usa la marca de agua" if ruta else
                                   "El logo sale tenue en el centro de cada página del PDF")

    def elegir_membrete(self) -> None:
        ruta, _ = QFileDialog.getOpenFileName(self, "Hoja membretada", str(Path.home()),
                                              "Imagen o PDF (*.png *.jpg *.jpeg *.pdf)")
        if not ruta:
            return
        destino = self.datos.fotos / f"membrete-{nuevo_id()[:4]}.png"
        if ruta.lower().endswith(".pdf"):
            if not pdf_a_imagen(Path(ruta), destino):
                QMessageBox.warning(self, "Hoja membretada", "No se pudo leer ese PDF. Pruebe con una imagen "
                                                             "(PNG o JPG) de la hoja.")
                return
        else:
            destino = destino.with_suffix(Path(ruta).suffix.lower())
            shutil.copy2(ruta, destino)
        self.datos.empresa.membrete = destino.name
        self.datos.empresa.marca_agua_intensidad = 100.0      # el membrete se ve completo; se puede bajar después
        self.datos.guardar()
        self.mostrar()
        self.v.statusBar().showMessage("Hoja membretada guardada. Use «Previsualización» para ajustar los "
                                       "espacios.", 8000)

    def quitar_membrete(self) -> None:
        self.datos.empresa.membrete = ""
        self.datos.guardar()
        self._mostrar_membrete()

    def ver_ejemplo(self) -> Path | None:
        """PDF de prueba con esta empresa: la proforma abierta si tiene módulos, si no una con el primer módulo."""
        import tempfile
        actual = self.v.pest_proforma.p
        p = copy.deepcopy(actual) if actual.items else self.datos.nueva_proforma()
        p.empresa_id = self.datos.empresa.id
        if not p.items and self.datos.modulos:
            p.items.append(self.datos.item_de(self.datos.modulos[0]))
            p.titulo = p.titulo or "EJEMPLO"
        destino = Path(tempfile.gettempdir()) / f"Ejemplo proforma - {nuevo_id()[:4]}.pdf"
        try:
            informes.pdf_cliente(p, self.datos, destino)
        except Exception as e:  # noqa: BLE001 - se informa al usuario
            QMessageBox.warning(self, "No se pudo armar el ejemplo", str(e))
            return None
        abrir_archivo(destino)
        return destino

    def _mostrar_logo(self):
        ruta = self.datos.ruta_foto(self.datos.empresa.logo)
        self.logo.setPixmap(QPixmap(str(ruta)).scaled(216, 116, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                            if ruta else QPixmap())
        self.logo.setText("" if ruta else "Sin logo")

    def nueva(self) -> None:
        e = Empresa(id=nuevo_id(), nombre="NUEVA EMPRESA")
        self.datos.empresas.append(e)
        self.datos.empresa_activa = e.id
        self.datos.guardar()
        self.refrescar()
        self.v.pest_proforma.refrescar_empresas()
        self.campos["nombre"].setFocus()
        self.campos["nombre"].selectAll()

    def eliminar(self) -> None:
        e = self.datos.empresa
        if len(self.datos.empresas) == 1:
            QMessageBox.information(self, "Eliminar", "Debe quedar al menos una empresa.")
            return
        usadas = sum(1 for p in self.datos.proformas if p.empresa_id == e.id)
        aviso = f"\n\n{usadas} proforma(s) guardada(s) la usan; pasarán a usar otra empresa." if usadas else ""
        if QMessageBox.question(self, "Eliminar", f"¿Eliminar la empresa «{e.nombre}»?{aviso}") != QMessageBox.Yes:
            return
        self.datos.empresas.remove(e)
        self.datos.empresa_activa = self.datos.empresas[0].id
        self.datos.guardar()
        self.refrescar()
        self.v.pest_proforma.refrescar_empresas()

    def elegir_logo(self):
        ruta, _ = QFileDialog.getOpenFileName(self, "Logo", str(Path.home()), "Imágenes (*.png *.jpg *.jpeg *.svg)")
        if ruta:
            destino = self.datos.fotos / f"logo-{nuevo_id()[:4]}{Path(ruta).suffix.lower()}"
            shutil.copy2(ruta, destino)
            self.datos.empresa.logo = destino.name
            self.datos.guardar()
            self._mostrar_logo()
            self.v.statusBar().showMessage(f"Logo guardado para «{self.datos.empresa.nombre}». Los PDF nuevos ya "
                                           "salen con este logo.", 8000)

    def guardar(self, *_a):
        if self._cargando:
            return
        e = self.datos.empresa
        for atributo, w in self.campos.items():
            setattr(e, atributo, w.text().strip())
        e.margen = self.margen.value()
        e.iva = self.iva.currentData()
        e.validez_dias = self.validez.value()
        e.membrete_sup, e.membrete_inf = self.memb_sup.value(), self.memb_inf.value()
        e.marca_agua, e.marca_agua_intensidad = self.marca_agua.isChecked(), self.intensidad.value()
        self.datos.guardar()
        it = self.lista.currentItem()
        if it is not None:
            it.setText("★  " + (e.nombre or "(sin nombre)"))
        self.v.pest_proforma.refrescar_empresas()


# =============================================================================================
class VentanaPrincipal(QMainWindow):
    def __init__(self, datos: Datos | None = None):
        super().__init__()
        self.datos = datos or Datos()
        from .. import NOMBRE_APP
        self.setWindowTitle(NOMBRE_APP)
        self.resize(1280, 820)
        self.setStyleSheet(ESTILO)
        self.pestanas = QTabWidget()
        self.pest_clientes = None
        self.pest_historial = None
        self.pest_proforma = PestanaProforma(self)
        self.pest_historial = PestanaHistorial(self)
        self.pest_modulos = PestanaModulos(self)
        self.pest_materiales = PestanaMateriales(self)
        self.pest_clientes = PestanaClientes(self)
        self.pest_empresa = PestanaEmpresa(self)
        self.pest_adicionales = PestanaAdicionales(self)
        self.pest_costos = PestanaCostos(self)
        for w, t in ((self.pest_empresa, "Datos de mi empresa"), (self.pest_clientes, "Clientes"),
                     (self.pest_materiales, "Materiales y precios"), (self.pest_modulos, "Módulos"),
                     (self.pest_adicionales, "Adicionales"), (self.pest_proforma, "Proforma"),
                     (self.pest_historial, "Historial"), (self.pest_costos, "Costo/gasto proyecto")):
            self.pestanas.addTab(w, t)
        self.pestanas.setCurrentWidget(self.pest_proforma)     # abre directo en la proforma
        self.pestanas.currentChanged.connect(self._cambio_pestana)
        central = QWidget()
        lay = QVBoxLayout(central)
        lay.setContentsMargins(12, 10, 12, 6)
        lay.addWidget(self.pestanas)
        self.setCentralWidget(central)

    def _cambio_pestana(self, i: int) -> None:
        w = self.pestanas.widget(i)
        if w is self.pest_proforma:
            self.pest_proforma.refrescar_catalogo()
        elif w is self.pest_modulos:
            self.pest_modulos._llenar_materiales()
        elif w is self.pest_historial:
            self.pest_historial.refrescar()
        elif w is self.pest_adicionales:
            self.pest_adicionales.refrescar()
        elif w is self.pest_costos:
            self.pest_costos.refrescar()

    def importar_excel(self, ruta: str | None = None) -> bool:
        if not ruta:
            inicio = Path.home() / "Descargas"
            ruta, _ = QFileDialog.getOpenFileName(self, "Excel de proformas", str(inicio if inicio.is_dir()
                                                                                   else Path.home()),
                                                  "Excel (*.xlsx *.xlsm)")
        if not ruta:
            return False
        try:
            r = importar(Path(ruta), self.datos)
        except Exception as e:  # noqa: BLE001 - se informa al usuario
            QMessageBox.warning(self, "No se pudo importar", str(e))
            return False
        self.pest_proforma.refrescar_catalogo()
        self.pest_modulos.refrescar()
        self.pest_materiales.refrescar()
        self.pest_clientes.refrescar()
        QMessageBox.information(self, "Importado", f"Se agregaron {r['materiales']} materiales, {r['modulos']} "
                                                   f"módulos, {r['clientes']} clientes y {r['fotos']} fotos nuevos.\n\n"
                                                   f"{r['sin_cambios']} ya existían con el mismo nombre y no se "
                                                   "modificaron.")
        return True

    # --- pasar módulos / historial a otra PC ----------------------------------------------------
    def exportar_paquete(self, tipo: str, ruta: str | None = None) -> bool:
        modulos = tipo == "modulos"
        if not (self.datos.modulos if modulos else self.datos.proformas):
            QMessageBox.information(self, "Exportar", "Todavía no hay " + ("módulos" if modulos else "proformas")
                                    + " para exportar.")
            return False
        if not ruta:
            inicio = Path.home() / "Descargas"
            from .. import NOMBRE_APP
            nombre = ("Módulos" if modulos else "Historial") + f" - {NOMBRE_APP} {dt.date.today():%d-%m-%Y}.zip"
            ruta, _ = QFileDialog.getSaveFileName(self, "Exportar " + ("módulos" if modulos else "historial"),
                                                  str((inicio if inicio.is_dir() else Path.home()) / nombre),
                                                  "Paquete (*.zip)")
        if not ruta:
            return False
        if not ruta.lower().endswith(".zip"):
            ruta += ".zip"
        try:
            n = (paquete.exportar_modulos if modulos else paquete.exportar_historial)(self.datos, Path(ruta))
        except Exception as e:  # noqa: BLE001 - se informa al usuario
            QMessageBox.warning(self, "No se pudo exportar", str(e))
            return False
        que = f"{n} módulos" if modulos else f"{n} proformas"
        pestana = "Módulos" if modulos else "Historial"
        QMessageBox.information(self, "Exportado", f"Se exportaron {que} a:\n{ruta}\n\nEn la otra PC: pestaña "
                                f"{pestana} → «{'Importar…' if modulos else 'Importar historial…'}» y elija este archivo.")
        return True

    def importar_paquete(self, tipo: str, ruta: str | None = None, reemplazar: bool | None = None) -> bool:
        modulos = tipo == "modulos"
        if not ruta:
            inicio = Path.home() / "Descargas"
            ruta, _ = QFileDialog.getOpenFileName(self, "Importar " + ("módulos" if modulos else "historial"),
                                                  str(inicio if inicio.is_dir() else Path.home()), "Paquete (*.zip)")
        if not ruta:
            return False
        try:
            if reemplazar is None:
                if modulos:
                    rep = paquete.modulos_repetidos(self.datos, Path(ruta))
                    lista = "\n".join(f"• {n}" for n in rep[:12]) + ("\n…" if len(rep) > 12 else "")
                    pregunta = f"Estos {len(rep)} módulos ya existen aquí con el mismo nombre:\n\n{lista}"
                else:
                    rep = paquete.proformas_repetidas(self.datos, Path(ruta))
                    lista = ", ".join(f"{n:04d}" for n in rep[:20]) + ("…" if len(rep) > 20 else "")
                    pregunta = f"Estas {len(rep)} proformas ya están aquí: N.º {lista}"
                reemplazar = False
                if rep:
                    caja = QMessageBox(QMessageBox.Question, "Ya existen", pregunta + "\n\n¿Qué hago con ellas?",
                                       parent=self)
                    b_rep = caja.addButton("Reemplazarlas con las del archivo", QMessageBox.AcceptRole)
                    b_dej = caja.addButton("Dejar las de aquí", QMessageBox.RejectRole)
                    caja.setEscapeButton(caja.addButton("Cancelar", QMessageBox.DestructiveRole))
                    caja.exec()
                    if caja.clickedButton() not in (b_rep, b_dej):
                        return False
                    reemplazar = caja.clickedButton() is b_rep
            if modulos:
                r = paquete.importar_modulos(self.datos, Path(ruta), reemplazar)
            else:
                r = paquete.importar_historial(self.datos, Path(ruta), reemplazar)
        except Exception as e:  # noqa: BLE001 - se informa al usuario
            QMessageBox.warning(self, "No se pudo importar", str(e))
            return False
        self.pest_proforma.refrescar_catalogo()
        self.pest_modulos.refrescar()
        self.pest_materiales.refrescar()
        self.pest_clientes.refrescar()
        self.pest_historial.refrescar()
        self.pest_empresa.refrescar()
        if modulos:
            texto = (f"Módulos nuevos: {r['modulos']}\nReemplazados: {r['reemplazados']}\n"
                     f"Dejados como estaban: {r['omitidos']}\nMateriales nuevos agregados: {r['materiales']}")
        else:
            texto = (f"Proformas nuevas: {r['proformas']}\nReemplazadas: {r['reemplazadas']}\n"
                     f"Dejadas como estaban: {r['omitidas']}\nClientes nuevos: {r['clientes']}\n"
                     f"Empresas nuevas: {r['empresas']}\nGastos: {r['gastos']}")
            if r["renumeradas"]:
                texto += (f"\n\n{r['renumeradas']} proforma(s) recibieron otro N.º porque el suyo ya estaba "
                          "ocupado aquí por otra proforma.")
        QMessageBox.information(self, "Importado", texto)
        return True

    def exportar_materiales_excel(self) -> bool:
        if not self.datos.materiales:
            QMessageBox.information(self, "Exportar", "Todavía no hay materiales para exportar.")
            return False
        inicio = Path.home() / "Descargas"
        destino = (inicio if inicio.is_dir() else Path.home()) / "Materiales - Proformador Ágil.xlsx"
        ruta, _ = QFileDialog.getSaveFileName(self, "Exportar materiales a Excel", str(destino), "Excel (*.xlsx)")
        if not ruta:
            return False
        if not ruta.lower().endswith(".xlsx"):
            ruta += ".xlsx"
        try:
            n = exportar_materiales(self.datos, Path(ruta))
        except Exception as e:  # noqa: BLE001 - se informa al usuario
            QMessageBox.warning(self, "No se pudo exportar", str(e))
            return False
        QMessageBox.information(self, "Exportado", f"Se exportaron {n} materiales a:\n{ruta}\n\nEn la otra máquina: "
                                "Materiales → «Importar desde Excel…» y elija este archivo.")
        return True
