import pytest
from openpyxl import load_workbook

from proformaapp import informes
from proformaapp.importar import importar
from proformaapp.modelo import Adicional, Datos


@pytest.fixture
def datos(tmp_path, excel):
    d = Datos(tmp_path / "datos")
    r = importar(excel, d)
    assert r == {"materiales": 4, "modulos": 2, "clientes": 1, "fotos": 0, "sin_cambios": 0}
    return d


def test_importa_recetas_y_clientes(datos):
    alfa, beta = datos.modulos
    assert alfa.nombre == "Módulo alfa de prueba" and alfa.descripcion == "- 1 BASE\n- LUCES"
    assert (alfa.ancho, alfa.alto, alfa.prof) == (1.2, 2.4, 0.6)
    assert beta.nombre == "Módulo beta"
    # ALFA: 2 tableros (200) + 3 led (30) + diseño 2 (100) + inversión 1 (50)
    assert datos.costo_modulo(alfa) == 380 and datos.costo_modulo(alfa, ["diseno", "inversion"]) == 230
    assert [m.tipo for m in datos.materiales] == ["material", "material", "diseno", "inversion"]
    c = datos.clientes[0]
    assert (c.nombre, c.ruc, c.correo) == ("EMPRESA FICTICIA S.A.", "1799999999001", "compras@ejemplo.com")
    # se guardó y se vuelve a leer igual
    otra = type(datos)(datos.carpeta)
    assert [m.nombre for m in otra.modulos] == ["Módulo alfa de prueba", "Módulo beta"]


def test_exportar_materiales_ida_y_vuelta(datos, tmp_path):
    from proformaapp.importar import exportar_materiales, importar
    xlsx = tmp_path / "materiales.xlsx"
    n = exportar_materiales(datos, xlsx)
    assert n == len(datos.materiales)
    # en otra máquina (base vacía) se reimporta y queda igual
    nueva = type(datos)(tmp_path / "otra")
    r = importar(xlsx, nueva)
    assert r["materiales"] == n and r["modulos"] == 0
    assert [(m.nombre, round(m.precio, 2)) for m in nueva.materiales] == \
           [(m.nombre, round(m.precio, 2)) for m in datos.materiales]


def test_calculos_25_por_ciento(datos):
    alfa, beta = datos.modulos
    p = datos.nueva_proforma()
    p.cliente_id = datos.clientes[0].id
    p.items += [datos.item_de(alfa, 2), datos.item_de(beta, 1)]
    p.adicionales.append(Adicional("LOGO", 3, 75))
    # costo: 2×380 + 1×(100+50+50) + 3×75 = 760 + 200 + 225
    assert p.costo_total() == 1185
    assert p.precio_unitario(p.items[0]) == 475          # 380 × 1,25
    assert p.subtotal() == pytest.approx(1481.25) and p.ganancia() == pytest.approx(296.25)
    assert p.total() == p.subtotal()                     # artesano: sin IVA
    p.no_cobrar = ["inversion"]                          # cobra diseño, no inversión
    assert p.costo_total() == 2 * 330 + 150 + 225
    p.no_cobrar = ["diseno", "inversion"]                # sin diseño ni inversión
    assert p.costo_total() == 2 * 230 + 100 + 225
    p.iva = "15"
    assert p.iva_valor() == pytest.approx(round(p.subtotal() * 0.15, 2))
    # la proforma guarda los precios del momento: cambiar un precio no la altera
    datos.materiales[0].precio = 999
    assert p.items[0].costo_unitario(p.no_cobrar) == 230
    datos.actualizar_precios(p)                          # salvo que se pida
    assert p.items[0].costo_unitario(p.no_cobrar) == 2 * 999 + 30
    mats = {m["nombre"]: m["cantidad"] for m in p.materiales_consolidados()}
    assert mats == {"TABLERO PRUEBA": 5, "LED PRUEBA": 6}  # 2×2 + 1, 2×3 (diseño excluido)


def test_informes(datos, tmp_path):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    alfa = datos.modulos[0]
    datos.empresa.nombre = "TALLER DE PRUEBA"
    p = datos.nueva_proforma()
    p.cliente_id, p.titulo = datos.clientes[0].id, "Exhibición de prueba"
    p.items.append(datos.item_de(alfa, 2))
    datos.guardar_proforma(p)
    html = informes.html_cliente(p, datos)
    assert "EMPRESA FICTICIA S.A." in html and "TALLER DE PRUEBA" in html and "$ 950,00" in html
    assert "380" not in html.replace("1799999999001", "")         # el cliente no ve los costos
    pdf = informes.pdf_cliente(p, datos, tmp_path / "c.pdf")
    assert pdf.read_bytes()[:4] == b"%PDF" and pdf.stat().st_size > 1000
    x = informes.excel_costos(p, datos, tmp_path / "c.xlsx")
    wb = load_workbook(x)
    assert wb.sheetnames == ["Resumen", "Materiales a comprar", "Detalle por módulo"]
    resumen = [c for fila in wb["Resumen"].values for c in fila if c is not None]
    assert "Su ganancia" in resumen and 190 in resumen and 760 in resumen    # ganancia 950 - 760
    assert informes.nombre_archivo(p, datos, "Cliente", ".pdf") == "Proforma 0001 - EMPRESA FICTICIA S.A. - Cliente.pdf"


def test_ventana(datos, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication, QFileDialog
    app = QApplication.instance() or QApplication([])
    from proformaapp.ui import ventana as v
    w = v.VentanaPrincipal(datos)
    pp = w.pest_proforma
    pp.buscar.setText("alfa")
    pp.agregar_elegido()
    pp.t_items.item(0, 1).setText("2")
    app.processEvents()
    w.pest_adicionales.agregar({"descripcion": "LOGO", "costo": 75, "por": "modulos"})
    assert pp.p.adicionales[0].cantidad == 2
    pp.cliente.setCurrentIndex(1)
    assert pp.lbl_costo.text() == "$ 910,00" and pp.lbl_ganancia.text() == "$ 227,50"
    assert not hasattr(pp, "opcionales")                # ya no hay casillas «Cobrar …»: todo se cobra
    abiertos = []
    monkeypatch.setattr(v, "abrir_archivo", lambda r: abiertos.append(r))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(tmp_path / "x.xlsx"), ""))
    pp.generar_excel()
    assert abiertos == [tmp_path / "x.xlsx"] and len(datos.proformas) == 1
    assert w.pest_historial.t.rowCount() == 1
    w.close()


def test_proforma_elige_modulos_y_se_edita_en_modulos(datos):
    """La proforma solo elige módulos (con buscador); la receta se cambia en Módulos y la proforma abierta
    toma el cambio."""
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from proformaapp.ui import ventana as v
    w = v.VentanaPrincipal(datos)
    pp, pm = w.pest_proforma, w.pest_modulos

    def visibles():
        return [pp.catalogo.item(f, 0).text() for f in range(pp.catalogo.rowCount())
                if not pp.catalogo.isRowHidden(f)]

    assert visibles() == ["Módulo alfa de prueba", "Módulo beta"]
    pp.buscar.setText("BETA")
    assert visibles() == ["Módulo beta"]
    pp.agregar_elegido()
    pp.t_items.item(0, 1).setText("2")
    app.processEvents()
    assert pp.p.items[0].cantidad == 2 and pp.lbl_costo.text() == "$ 400,00"     # 2 × (100 + 50 + 50)

    pp.editar_en_modulos()                             # salta a Módulos con ese módulo elegido
    assert w.pestanas.currentWidget() is pm and pm.actual().nombre == "Módulo beta"
    pm.c_mat.setEditText("led")
    pm._agregar_escrito()
    app.processEvents()
    pm.t_receta.item(pm.t_receta.currentRow(), 1).setText("3")
    app.processEvents()
    w.pestanas.setCurrentWidget(pp)
    assert pp.p.items[0].cantidad == 2 and pp.lbl_costo.text() == "$ 460,00"     # + 2 × 3 LED de 10
    w.close()


def test_proforma_vieja_sin_diseno_se_convierte(datos):
    """Las proformas guardadas con la casilla única desmarcada quedan sin cobrar diseño ni inversión."""
    import json
    p = datos.nueva_proforma()
    p.items.append(datos.item_de(datos.modulos[0], 1))
    datos.guardar_proforma(p)
    crudo = json.loads(datos.archivo.read_text(encoding="utf-8"))
    viejo = crudo["proformas"][0]
    viejo.pop("no_cobrar")
    crudo["version"] = 1
    viejo["incluir_diseno"] = False
    datos.archivo.write_text(json.dumps(crudo), encoding="utf-8")
    otra = type(datos)(datos.carpeta)
    assert otra.proformas[0].costo_total() == 230


def test_modulos_buscador_de_materiales(datos):
    """En Módulos se escribe parte del nombre (sin tildes) y Enter agrega el material a la receta."""
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from proformaapp.ui import ventana as v
    w = v.VentanaPrincipal(datos)
    pm = w.pest_modulos
    pm.lista.setCurrentRow(1)                         # Módulo beta: sin LED
    beta = pm.actual()
    led = next(m for m in datos.materiales if m.nombre == "LED PRUEBA")
    assert led.id not in beta.receta
    pm.c_mat.setEditText("led")
    pm._agregar_escrito()
    app.processEvents()
    assert beta.receta[led.id] == 1 and pm.c_mat.currentText() == ""
    # la lista filtra por la palabra sin tilde
    pm.completador.setCompletionPrefix("diseno")
    assert pm.completador.completionCount() == 1
    w.close()


def test_materiales_sin_interruptores(datos):
    """Materiales y precios solo tiene material, unidad y precio (diseño e inversión son materiales normales)."""
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from proformaapp.ui import ventana as v
    w = v.VentanaPrincipal(datos)
    pm = w.pest_materiales
    assert [pm.t.horizontalHeaderItem(c).text() for c in range(pm.t.columnCount())] == \
        ["Material", "Unidad", "Precio"]
    # una proforma nueva cobra DISEÑO e INVERSIÓN como cualquier material: 2 tableros + 3 led + 2 diseño + 1 inv.
    pp = w.pest_proforma
    pp.buscar.setText("alfa")
    pp.agregar_elegido()
    assert pp.p.no_cobrar == [] and pp.lbl_costo.text() == "$ 380,00"
    w.close()


def test_datos_version_1_separa_inversion(tmp_path):
    """Los datos guardados antes (DISEÑO e INVERSIÓN con el mismo tipo) se separan al abrir."""
    import json
    carpeta = tmp_path / "d"
    carpeta.mkdir()
    (carpeta / "datos.json").write_text(json.dumps({"version": 1, "materiales": [
        {"id": "a", "nombre": "DISEÑO", "precio": 50, "tipo": "diseno"},
        {"id": "b", "nombre": "INVERSION", "precio": 50, "tipo": "diseno"}]}), encoding="utf-8")
    d = Datos(carpeta)
    assert [m.tipo for m in d.materiales] == ["diseno", "inversion"]


# ------------------------------------------------------------------------------------------------
# Lote 2: varias empresas, condiciones, adicionales repartidos, importación sin pisar, historial, PDF, gastos
# ------------------------------------------------------------------------------------------------
def test_datos_v2_pasan_a_varias_empresas(tmp_path):
    import json
    carpeta = tmp_path / "d"
    carpeta.mkdir()
    (carpeta / "datos.json").write_text(json.dumps({"version": 2, "empresa": {
        "nombre": "TALLER", "ruc": "1700000000001", "condiciones": ["ENTREGA INCLUIDA"],
        "plantillas": [{"descripcion": "LOGO", "costo": 75, "por": "modulos"}]},
        "proformas": [{"id": "p1", "numero": 1, "fecha": "2026-11-06"}]}), encoding="utf-8")
    d = Datos(carpeta)
    assert [e.nombre for e in d.empresas] == ["TALLER"] and d.empresa.nombre == "TALLER"
    assert d.condiciones == ["ENTREGA INCLUIDA"] and d.plantillas[0]["descripcion"] == "LOGO"
    vieja = d.proformas[0]
    assert vieja.condiciones == ["ENTREGA INCLUIDA"] and vieja.empresa_id == d.empresa.id
    d.guardar()
    otra = Datos(carpeta)                                       # se guarda y se relee en el formato nuevo
    assert otra.empresa.nombre == "TALLER" and otra.proformas[0].condiciones == ["ENTREGA INCLUIDA"]


def test_adicional_repartido_en_los_modulos(datos):
    from proformaapp.modelo import Item
    p = datos.nueva_proforma()
    p.margen = 25
    a = Item(modulo_id="", nombre="A", cantidad=1, receta=[{"material": "x", "nombre": "X", "cantidad": 1,
                                                           "precio": 100, "tipo": "material"}])
    b = Item(modulo_id="", nombre="B", cantidad=3, receta=[{"material": "x", "nombre": "X", "cantidad": 1,
                                                           "precio": 100, "tipo": "material"}])
    p.items += [a, b]
    p.adicionales.append(Adicional("LOGO", 1, 40, distribuir=True))      # precio 50: 25 % a A y 75 % a B
    assert [round(x[1], 2) for x in p.reparto()] == [0.25, 0.75]
    assert p.precio_unitario(a) == 137.5 and p.precio_unitario(b) == 137.5    # 125 + 12,5 y 125 + 37,5/3
    assert p.subtotal() == 550 and p.costo_total() == 440 and p.ganancia() == 110
    html = informes.html_cliente(p, datos)
    assert "LOGO" not in html                                   # no sale como línea aparte
    p.adicionales[0].distribuir = False
    assert p.precio_unitario(a) == 125 and p.subtotal() == 550 and "LOGO" in informes.html_cliente(p, datos)


def test_importar_no_modifica_lo_existente(datos, excel):
    from proformaapp.importar import importar
    tablero = next(m for m in datos.materiales if m.nombre == "TABLERO PRUEBA")
    tablero.precio = 123                                        # el usuario cambió el precio
    alfa = datos.modulos[0]
    alfa.descripcion = "MI DESCRIPCIÓN"
    datos.materiales = [m for m in datos.materiales if m.nombre != "LED PRUEBA"]   # y borró uno
    r = importar(excel, datos)
    assert r["materiales"] == 1 and r["modulos"] == 0 and r["clientes"] == 0      # solo vuelve el LED
    assert tablero.precio == 123 and alfa.descripcion == "MI DESCRIPCIÓN"
    assert [m.nombre for m in datos.materiales].count("TABLERO PRUEBA") == 1


def test_pdf_logo_grande_sin_imagenes_y_condiciones(datos, tmp_path):
    from PySide6.QtGui import QColor, QImage
    img = QImage(10, 10, QImage.Format_RGB32)
    img.fill(QColor("red"))
    img.save(str(datos.fotos / "logo.png"))
    img.save(str(datos.fotos / "foto.png"))
    datos.empresa.logo = "logo.png"
    datos.modulos[0].foto = "foto.png"
    p = datos.nueva_proforma()
    p.items.append(datos.item_de(datos.modulos[0], 1))
    p.condiciones = ["SOLO ESTA CONDICIÓN"]
    html = informes.html_cliente(p, datos)
    assert 'height="140"' in html and "foto.png" in html and "SOLO ESTA CONDICIÓN" in html
    assert "ENTREGA EN PUNTO DE VENTA" not in html
    p.con_imagenes = False
    html = informes.html_cliente(p, datos)
    assert "foto.png" not in html and "logo.png" in html        # sin fotos, pero con logo


XML_SRI = """<?xml version="1.0" encoding="UTF-8"?>
<autorizacion><estado>AUTORIZADO</estado><numeroAutorizacion>0611202601179</numeroAutorizacion>
<comprobante><![CDATA[<?xml version="1.0" encoding="UTF-8"?>
<factura id="comprobante" version="1.1.0">
 <infoTributaria><ambiente>2</ambiente><razonSocial>MADERAS DEL VALLE S.A.</razonSocial>
  <ruc>1791234567001</ruc><codDoc>01</codDoc><estab>002</estab><ptoEmi>001</ptoEmi>
  <secuencial>000004567</secuencial></infoTributaria>
 <infoFactura><fechaEmision>05/11/2026</fechaEmision><totalSinImpuestos>200.00</totalSinImpuestos>
  <totalConImpuestos><totalImpuesto><codigo>2</codigo><codigoPorcentaje>4</codigoPorcentaje>
   <baseImponible>200.00</baseImponible><valor>30.00</valor></totalImpuesto></totalConImpuestos>
  <importeTotal>230.00</importeTotal></infoFactura>
 <detalles><detalle><descripcion>MDP BLANCO 15MM</descripcion></detalle>
  <detalle><descripcion>CANTO PVC</descripcion></detalle></detalles>
</factura>]]></comprobante></autorizacion>"""


def test_leer_factura_xml_y_pdf(tmp_path):
    from proformaapp import comprobantes
    ruta = tmp_path / "f.xml"
    ruta.write_text(XML_SRI, encoding="utf-8")
    d = comprobantes.leer_xml(ruta)
    assert d == {"proveedor": "MADERAS DEL VALLE S.A.", "ruc": "1791234567001", "documento": "002-001-000004567",
                 "fecha": "2026-11-05", "subtotal": 200.0, "iva": 30.0, "total": 230.0,
                 "descripcion": "MDP BLANCO 15MM; CANTO PVC"}
    texto = ("FERRETERIA EL CLAVO\nR.U.C.: 1798765432001\nFACTURA\nNo. 001-002-000000089\n"
             "FECHA EMISIÓN: 03/11/2026\nSUBTOTAL SIN IMPUESTOS 1.000,00\nIVA 15% 150,00\nVALOR TOTAL 1.150,00")
    d = comprobantes.datos_de_texto(texto)
    assert (d["proveedor"], d["ruc"], d["documento"], d["fecha"]) == ("FERRETERIA EL CLAVO", "1798765432001",
                                                                      "001-002-000000089", "2026-11-03")
    assert (d["subtotal"], d["iva"], d["total"]) == (1000.0, 150.0, 1150.0)
    # un PDF de verdad: se escribe con Qt y se vuelve a leer
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from PySide6.QtGui import QPdfWriter, QTextDocument
    pdf = tmp_path / "f.pdf"
    doc = QTextDocument()
    doc.setPlainText(texto)
    doc.print_(QPdfWriter(str(pdf)))
    if not comprobantes.texto_pdf(pdf).strip():
        import pytest
        pytest.skip("QtPdf no extrae texto del PDF en esta plataforma; la lectura de facturas en PDF quedaría"
                    " limitada aquí (el XML del SRI y la carga manual sí funcionan).")
    d = comprobantes.leer_pdf(pdf)
    assert d["ruc"] == "1798765432001" and d["total"] == 1150.0


def test_pestanas_nuevas(datos, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication, QFileDialog
    app = QApplication.instance() or QApplication([])
    from proformaapp.ui import ventana as v
    w = v.VentanaPrincipal(datos)
    nombres = [w.pestanas.tabText(i) for i in range(w.pestanas.count())]
    assert nombres == ["Datos de mi empresa", "Clientes", "Materiales y precios", "Módulos", "Adicionales",
                       "Proforma", "Historial", "Costo/gasto proyecto"]
    # empresas: crear una nueva la deja elegida y aparece en la proforma
    pe, pp = w.pest_empresa, w.pest_proforma
    pe.nueva()
    pe.campos["nombre"].setText("SEGUNDA EMPRESA")
    assert pe.lista.count() == 2 and "SEGUNDA EMPRESA" in pe.lista.item(1).text()
    assert pp.empresa.findText("SEGUNDA EMPRESA") >= 0
    pp.nueva()
    assert pp.p.empresa_id == datos.empresa.id and pp.empresa.currentText() == "SEGUNDA EMPRESA"
    # condiciones: marcar, crear
    pp.nueva_cond.setText("incluye instalación")
    pp.agregar_condicion()
    assert "INCLUYE INSTALACIÓN" in datos.condiciones and "INCLUYE INSTALACIÓN" in pp.p.condiciones
    pp.l_cond.item(0).setCheckState(v.Qt.Unchecked)
    assert datos.condiciones[0] not in pp.p.condiciones
    # adicionales en su pestaña, repartidos
    pp.buscar.setText("alfa")
    pp.agregar_elegido()
    pa = w.pest_adicionales
    w.pestanas.setCurrentWidget(pa)
    pa.agregar({"descripcion": "LOGO", "costo": 80, "por": "uno"})
    assert pa.t.rowCount() == 1 and pp.p.total() == 575              # 380 × 1,25 + 80 × 1,25
    pa._repartir(0, True)
    assert pa.t_rep.rowCount() == 1 and pp.p.precio_unitario(pp.p.items[0]) == 575
    assert "repartido en los módulos $ 100,00" in pp.lbl_adic.text()
    # historial: número primero y fecha corta
    pp.cliente.setCurrentIndex(1)
    pp.guardar()
    w.pest_historial.refrescar()
    h = w.pest_historial.t
    assert h.horizontalHeaderItem(0).text() == "N.º" and h.item(0, 0).text() == "0001"
    assert h.item(0, 1).text() == v.informes.fecha_corta(pp.p.fecha) and "/" in h.item(0, 1).text()
    # costos: cargar una factura XML y ver ganancia
    xml = tmp_path / "f.xml"
    xml.write_text(XML_SRI, encoding="utf-8")
    pc = w.pest_costos
    w.pestanas.setCurrentWidget(pc)
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", lambda *a, **k: ([str(xml)], ""))
    pc.cargar_xml()
    assert pc.t.rowCount() == 1 and pc.cifras["gastado"].text() == "$ 230,00"
    assert pc.cifras["resultado"].text() == "$ 345,00" and "GANANCIA" in pc.lbl_estado.text()
    assert (datos.comprobantes / datos.gastos[0].archivo).is_file()
    pc.cargar_xml()                                                  # la misma factura no se repite
    assert pc.t.rowCount() == 1
    datos.gastos[0].total = 700
    pc.refrescar_gastos()
    assert "PÉRDIDA" in pc.lbl_estado.text() and pc.cifras["resultado"].text() == "$ -125,00"
    w.close()


def test_reparto_proporcional_al_precio():
    """Adicional repartido entre módulos de 60 y 40: cada uno recibe su % del precio, montos con 2 decimales que
    suman exacto."""
    from proformaapp.modelo import Adicional, Item, Proforma
    receta = lambda c: [{"material": "x", "nombre": "X", "unidad": "u", "tipo": "material", "cantidad": 1, "precio": c}]
    p = Proforma(id="p", numero=1, fecha="2026-11-06", margen=25,
                 items=[Item("a", "A", 1, receta=receta(48)), Item("b", "B", 1, receta=receta(32))],
                 adicionales=[Adicional("LOGO", 1, 80, distribuir=True)])
    # precios 60 y 40; adicional 80 + 25 % = 100 → 60 y 40
    rep = p.reparto()
    assert [round(pct, 4) for _i, pct, _m in rep] == [0.6, 0.4]
    assert [m for _i, _p, m in rep] == [60.0, 40.0]
    assert [p.precio_unitario(i) for i in p.items] == [120.0, 80.0]
    # tres módulos iguales y 100 a repartir: 33,34 + 33,33 + 33,33 = 100,00
    p.items = [Item(k, k, 1, receta=receta(10)) for k in "abc"]
    montos = [m for _i, _p, m in p.reparto()]
    assert round(sum(montos), 2) == 100.0 and all(round(m, 2) == m for m in montos)
