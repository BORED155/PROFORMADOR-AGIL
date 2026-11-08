"""Pestaña «Adicionales»: logo, transporte, viáticos… de la proforma abierta, con la opción de repartir su valor
entre los módulos (en proporción al precio de cada uno) en vez de cobrarlos como línea aparte."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QHBoxLayout, QLabel, QMenu, QPushButton, QSplitter,
                               QTableWidgetItem, QToolButton, QVBoxLayout, QWidget)

from ..modelo import Adicional, redondear
from .comun import Interruptor, centrado, dinero, item_texto, leer_numero, numero, tabla


class PestanaAdicionales(QWidget):
    POR = [("uno", "1"), ("modulos", "× número de módulos"), ("m2", "× m² de la exhibición")]

    def __init__(self, ventana):
        super().__init__()
        self.v = ventana
        self.datos = ventana.datos
        self._cargando = False

        self.lbl_proforma = QLabel()
        self.lbl_proforma.setObjectName("titulo")

        # --- adicionales de la proforma ---
        self.t = tabla(["Adicional", "Cant.", "Costo unit.", "Precio unit.", "Total cliente",
                        "Repartir en los módulos"])
        self.t.setEditTriggers(QAbstractItemView.AllEditTriggers)
        self.t.verticalHeader().setDefaultSectionSize(34)
        self.t.itemChanged.connect(self._editado)
        self.b_agregar = QToolButton()
        self.b_agregar.setText("＋ Agregar adicional  ▾")
        self.b_agregar.setPopupMode(QToolButton.InstantPopup)
        self.b_agregar.setMenu(QMenu(self.b_agregar))
        self.b_agregar.menu().aboutToShow.connect(self._menu)
        b_quitar = QPushButton("Quitar adicional")
        b_quitar.setObjectName("rojo")
        b_quitar.clicked.connect(self.quitar)
        b_volver = QPushButton("Volver a la proforma")
        b_volver.setObjectName("azul")
        b_volver.clicked.connect(lambda: self.v.pestanas.setCurrentWidget(self.v.pest_proforma))
        ayuda = QLabel("«Repartir en los módulos» (verde): el adicional no sale como línea aparte en la proforma; su "
                       "precio se suma a los módulos en proporción al precio de cada uno (ej.: 100 entre módulos de 60 y 40 → 60 y 40).")
        ayuda.setWordWrap(True)
        ayuda.setStyleSheet("color: #546e7a")

        # --- cómo se reparte ---
        self.t_rep = tabla(["Módulo", "Cant.", "% del precio", "Monto repartido", "Precio unit. final",
                            "Total cliente"])
        self.t_rep.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.lbl_resumen = QLabel()
        self.lbl_resumen.setStyleSheet("font-weight: bold; color: #37474f")

        # --- adicionales rápidos (plantillas) ---
        self.t_plant = tabla(["Adicional rápido", "Costo", "Cantidad automática"])
        self.t_plant.itemChanged.connect(self._plantilla_editada)
        b_pl = QPushButton("Agregar")
        b_pl.clicked.connect(self._agregar_plantilla)
        b_pl_q = QPushButton("Quitar")
        b_pl_q.clicked.connect(self._quitar_plantilla)

        arriba = QWidget()
        la = QVBoxLayout(arriba)
        la.setContentsMargins(0, 0, 0, 0)
        f1 = QHBoxLayout()
        f1.addWidget(self.lbl_proforma)
        f1.addStretch(1)
        f1.addWidget(self.b_agregar)
        f1.addWidget(b_quitar)
        f1.addWidget(b_volver)
        la.addLayout(f1)
        la.addWidget(ayuda)
        la.addWidget(self.t, 1)

        medio = QWidget()
        lm = QVBoxLayout(medio)
        lm.setContentsMargins(0, 0, 0, 0)
        t2 = QLabel("Cómo queda el reparto en los módulos")
        t2.setObjectName("titulo")
        lm.addWidget(t2)
        lm.addWidget(self.t_rep, 1)
        lm.addWidget(self.lbl_resumen)

        abajo = QWidget()
        lb = QVBoxLayout(abajo)
        lb.setContentsMargins(0, 0, 0, 0)
        f3 = QHBoxLayout()
        t3 = QLabel("Adicionales rápidos (los que salen en «Agregar adicional»)")
        t3.setObjectName("titulo")
        f3.addWidget(t3)
        f3.addStretch(1)
        f3.addWidget(b_pl)
        f3.addWidget(b_pl_q)
        lb.addLayout(f3)
        lb.addWidget(self.t_plant, 1)

        div = QSplitter(Qt.Vertical)
        for w in (arriba, medio, abajo):
            div.addWidget(w)
        div.setSizes([260, 220, 170])
        lay = QVBoxLayout(self)
        lay.addWidget(div)
        self._mostrar_plantillas()

    @property
    def p(self):
        return self.v.pest_proforma.p

    # --- mostrar ------------------------------------------------------------------------------
    def refrescar(self) -> None:
        p = self.p
        self.lbl_proforma.setText(f"Adicionales de la proforma N.º {p.numero:04d}" +
                                  (f" — {p.titulo}" if p.titulo else ""))
        self._cargando = True
        for f in range(self.t.rowCount()):           # los interruptores viejos se quitan antes de redibujar
            viejo = self.t.cellWidget(f, 5)
            if viejo is not None:
                viejo.hide()
                self.t.removeCellWidget(f, 5)
        self.t.setRowCount(len(p.adicionales))
        for f, a in enumerate(p.adicionales):
            pu = p.precio_adicional(a)
            for c, (texto, editable) in enumerate([(a.descripcion, True), (numero(a.cantidad), True),
                                                   (numero(a.costo), True), (dinero(pu), False),
                                                   (dinero(redondear(pu * a.cantidad)), False)]):
                self.t.setItem(f, c, item_texto(texto, editable, c >= 1))
            celda = QTableWidgetItem()
            celda.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.t.setItem(f, 5, celda)
            sw = Interruptor()
            sw.setChecked(a.distribuir)
            sw.toggled.connect(lambda si, f=f: self._repartir(f, si))
            self.t.setCellWidget(f, 5, centrado(sw))
        self._cargando = False

        reparto = p.reparto() if p.total_distribuido() else []
        self.t_rep.setRowCount(len(reparto))
        for f, (i, pct, monto) in enumerate(reparto):
            pu = p.precio_unitario(i)
            for c, texto in enumerate([i.nombre, numero(i.cantidad), f"{numero(pct * 100)} %", dinero(monto), dinero(pu),
                                       dinero(redondear(pu * i.cantidad))]):
                self.t_rep.setItem(f, c, item_texto(texto, alinear_derecha=c >= 1))
        aparte = sum(p.precio_adicional(a) * a.cantidad for a in p.adicionales_aparte())
        if p.adicionales and not p.items and p.total_distribuido():
            self.lbl_resumen.setText("Agregue módulos a la proforma para poder repartir los adicionales.")
        else:
            self.lbl_resumen.setText(f"Repartido en los módulos: {dinero(p.total_distribuido())}   ·   "
                                     f"Como línea aparte: {dinero(aparte)}   ·   Total de la proforma: "
                                     f"{dinero(p.total())}")

    def _cambio(self) -> None:
        self.v.pest_proforma.recalcular()
        self.refrescar()

    # --- editar -------------------------------------------------------------------------------
    def _editado(self, it: QTableWidgetItem) -> None:
        if self._cargando or not 0 <= it.row() < len(self.p.adicionales):
            return
        a = self.p.adicionales[it.row()]
        if it.column() == 0:
            a.descripcion = it.text()
        elif it.column() == 1:
            a.cantidad = max(0.0, leer_numero(it.text(), a.cantidad))
            a.por = "uno"                    # escrita a mano: ya no sigue a los módulos
        elif it.column() == 2:
            a.costo = max(0.0, leer_numero(it.text(), a.costo))
        self._cambio()

    def _repartir(self, fila: int, si: bool) -> None:
        if 0 <= fila < len(self.p.adicionales):
            self.p.adicionales[fila].distribuir = si
            self._cambio()

    def _menu(self) -> None:
        m = self.b_agregar.menu()
        m.clear()
        for pl in self.datos.plantillas:
            por = {"modulos": "× cada módulo", "m2": "× m² de la exhibición"}.get(pl.get("por"), "")
            m.addAction(f"{pl['descripcion']}  ({dinero(pl.get('costo', 0))} {por})".replace("  ()", ""),
                        lambda pl=pl: self.agregar(pl))
        m.addSeparator()
        m.addAction("Otro…", lambda: self.agregar({"descripcion": "OTRO", "costo": 0, "por": "uno"}))

    def agregar(self, plantilla: dict) -> None:
        p = self.p
        por = plantilla.get("por", "uno")
        p.adicionales.append(Adicional(plantilla["descripcion"], p.cantidad_por(por), float(plantilla.get("costo", 0)),
                                       por=por))
        self._cambio()

    def quitar(self) -> None:
        filas = sorted({i.row() for i in self.t.selectedIndexes()}, reverse=True) or \
            ([self.t.currentRow()] if self.t.currentRow() >= 0 else [])
        for f in filas:
            if 0 <= f < len(self.p.adicionales):
                del self.p.adicionales[f]
        self._cambio()

    # --- adicionales rápidos ------------------------------------------------------------------
    def _mostrar_plantillas(self) -> None:
        self._cargando = True
        pls = self.datos.plantillas
        self.t_plant.setRowCount(len(pls))
        for f, pl in enumerate(pls):
            self.t_plant.setItem(f, 0, item_texto(pl["descripcion"], True))
            self.t_plant.setItem(f, 1, item_texto(numero(pl.get('costo', 0)), True, True))
            combo = QComboBox()
            for codigo, texto in self.POR:
                combo.addItem(texto, codigo)
            combo.setCurrentIndex(max(0, combo.findData(pl.get("por", "uno"))))
            combo.currentIndexChanged.connect(lambda _i, f=f, c=combo: self._por(f, c.currentData()))
            self.t_plant.setCellWidget(f, 2, combo)
        self._cargando = False

    def _por(self, fila: int, valor: str) -> None:
        self.datos.plantillas[fila]["por"] = valor
        self.datos.guardar()

    def _plantilla_editada(self, it: QTableWidgetItem) -> None:
        if self._cargando:
            return
        pl = self.datos.plantillas[it.row()]
        if it.column() == 0:
            pl["descripcion"] = it.text().strip()
        elif it.column() == 1:
            pl["costo"] = max(0.0, leer_numero(it.text(), pl.get("costo", 0)))
        self.datos.guardar()

    def _agregar_plantilla(self) -> None:
        self.datos.plantillas.append({"descripcion": "NUEVO", "costo": 0.0, "por": "uno"})
        self.datos.guardar()
        self._mostrar_plantillas()
        self.t_plant.editItem(self.t_plant.item(self.t_plant.rowCount() - 1, 0))

    def _quitar_plantilla(self) -> None:
        f = self.t_plant.currentRow()
        if 0 <= f < len(self.datos.plantillas):
            del self.datos.plantillas[f]
            self.datos.guardar()
            self._mostrar_plantillas()
