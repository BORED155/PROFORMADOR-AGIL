import zipfile

import pytest
from openpyxl import Workbook, load_workbook

from proformaapp import comprobantes, informes, paquete
from proformaapp import importar as importar_mod
from proformaapp.importar import importar
from proformaapp.modelo import Adicional, Datos, Item, Material, Modulo, Proforma


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


def test_descripcion_estandar():
    from proformaapp.modelo import separar_descripcion, unir_descripcion
    t = unir_descripcion("Exhibidor", "MDF 18 mm", "- luces\n- acrílico")
    assert t == "Tipo: Exhibidor\nMateriales de fabricación: MDF 18 mm\nCaracterística específica:\n- luces\n- acrílico"
    assert separar_descripcion(t) == ["Exhibidor", "MDF 18 mm", "- luces\n- acrílico"]
    assert separar_descripcion("- texto viejo") == ["", "", "- texto viejo"]
    assert unir_descripcion("", "", "") == ""


def test_modulos_descripcion_en_tres_campos(datos):
    """Módulos muestra Tipo / Materiales / Característica; un texto viejo cae en Característica."""
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from proformaapp import informes
    from proformaapp.ui import ventana as v
    w = v.VentanaPrincipal(datos)
    pm = w.pest_modulos
    pm.lista.setCurrentRow(0)
    alfa = pm.actual()
    assert pm.d_tipo.text() == "" and pm.d_caract.toPlainText() == "- 1 BASE\n- LUCES"
    pm.d_tipo.setText("Exhibidor de piso")
    pm.d_materiales.setText("MDF 18 mm")
    assert alfa.descripcion == ("Tipo: Exhibidor de piso\nMateriales de fabricación: MDF 18 mm\n"
                                "Característica específica:\n- 1 BASE\n- LUCES")
    assert informes._linea_descripcion("Tipo: Exhibidor") == "<b>Tipo:</b> Exhibidor"


def test_paquete_modulos_ida_y_vuelta(datos, tmp_path):
    from proformaapp import paquete
    from proformaapp.modelo import Material, Modulo
    alfa = datos.modulos[0]
    (datos.fotos / "alfa.png").write_bytes(b"PNG-ALFA")
    alfa.foto, alfa.descripcion = "alfa.png", "Tipo: Exhibidor"
    zipf = tmp_path / "modulos.zip"
    assert paquete.exportar_modulos(datos, zipf) == 2
    # otra PC: ya tiene un material con el mismo nombre (otro precio) y un módulo con el mismo nombre
    otra = Datos(tmp_path / "otra")
    otra.materiales.append(Material("x1", "Led prueba", 7.0))
    otra.modulos.append(Modulo("m1", "MÓDULO BETA", descripcion="vieja"))
    assert paquete.modulos_repetidos(otra, zipf) == ["Módulo beta"]
    r = paquete.importar_modulos(otra, zipf)
    assert r == {"modulos": 1, "reemplazados": 0, "omitidos": 1, "materiales": 3}
    nuevo = next(m for m in otra.modulos if m.nombre == "Módulo alfa de prueba")
    assert nuevo.descripcion == "Tipo: Exhibidor" and (otra.fotos / nuevo.foto).read_bytes() == b"PNG-ALFA"
    led = next(m for m in otra.materiales if m.nombre == "Led prueba")
    assert led.precio == 7.0 and nuevo.receta[led.id] == 3          # se reutiliza el material existente
    assert otra.costo_modulo(nuevo) == 2 * 100 + 3 * 7 + 2 * 50 + 50
    # importar de nuevo reemplazando: no duplica, conserva el id del módulo de aquí
    r = paquete.importar_modulos(otra, zipf, reemplazar=True)
    assert r["reemplazados"] == 2 and r["modulos"] == 0 and r["materiales"] == 0 and len(otra.modulos) == 2
    beta = next(m for m in otra.modulos if m.nombre == "Módulo beta")
    assert beta.id == "m1" and beta.descripcion == ""
    assert len(Datos(otra.carpeta).modulos) == 2                      # quedó guardado
    with pytest.raises(ValueError, match="MÓDULOS"):
        paquete.importar_historial(otra, zipf)


def test_paquete_historial_ida_y_vuelta(datos, tmp_path):
    from proformaapp import paquete
    from proformaapp.modelo import Cliente, Gasto
    p = datos.nueva_proforma()
    p.cliente_id, p.titulo = datos.clientes[0].id, "Kywi"
    p.items.append(datos.item_de(datos.modulos[0], 2))
    (datos.fotos / "final.png").write_bytes(b"FINAL")
    p.imagen = "final.png"
    datos.guardar_proforma(p)
    (datos.comprobantes / "g1.xml").write_text("<factura/>")
    datos.gastos.append(Gasto("g1", p.id, proveedor="Ferretería", total=10, archivo="g1.xml"))
    datos.guardar()
    zipf = tmp_path / "historial.zip"
    assert paquete.exportar_historial(datos, zipf) == 1
    # otra PC: ya tiene el mismo cliente (otro id, mismo RUC) y una proforma N.º 1 distinta
    otra = Datos(tmp_path / "otra")
    otra.clientes.append(Cliente("c9", "Empresa Ficticia", ruc="1799999999001"))
    otra.guardar_proforma(otra.nueva_proforma())
    r = paquete.importar_historial(otra, zipf)
    assert (r["proformas"], r["renumeradas"], r["clientes"], r["gastos"]) == (1, 1, 0, 1)
    q = next(x for x in otra.proformas if x.id == p.id)
    assert q.numero == 2 and q.cliente_id == "c9" and q.total() == p.total()
    assert (otra.fotos / q.imagen).read_bytes() == b"FINAL"
    assert (otra.comprobantes / otra.gastos_de(q.id)[0].archivo).read_text() == "<factura/>"
    assert otra.empresa_de(q).nombre == datos.empresa_de(p).nombre
    # importar otra vez: sin reemplazar no duplica; reemplazando conserva su N.º y no duplica gastos
    assert paquete.proformas_repetidas(otra, zipf) == [1]
    assert paquete.importar_historial(otra, zipf)["omitidas"] == 1 and len(otra.proformas) == 2
    r = paquete.importar_historial(otra, zipf, reemplazar=True)
    assert r["reemplazadas"] == 1 and otra.proforma(p.id).numero == 2 and len(otra.gastos_de(p.id)) == 1


def test_botones_exportar_importar(datos, tmp_path):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from proformaapp.ui import ventana as v
    w = v.VentanaPrincipal(datos)
    p = datos.nueva_proforma()
    p.items.append(datos.item_de(datos.modulos[0]))
    datos.guardar_proforma(p)
    assert w.exportar_paquete("modulos", str(tmp_path / "m"))
    assert w.exportar_paquete("historial", str(tmp_path / "h.zip"))
    w2 = v.VentanaPrincipal(Datos(tmp_path / "otra"))
    assert w2.importar_paquete("modulos", str(tmp_path / "m.zip"))
    assert w2.importar_paquete("historial", str(tmp_path / "h.zip"))
    assert w2.pest_modulos.lista.count() == 2 and w2.pest_historial.t.rowCount() == 1
    assert len(w2.datos.empresas) == 1 and w2.datos.empresa.id == datos.empresa.id
    assert not w2.importar_paquete("modulos", str(tmp_path / "h.zip"))   # paquete equivocado: avisa


def test_condiciones_editables_y_casillas_visibles(datos):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPainter, QColor
    from PySide6.QtCore import QRectF
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from proformaapp.ui import ventana as v
    from proformaapp.ui.comun import pintar_casilla
    w = v.VentanaPrincipal(datos)
    pp = w.pest_proforma
    original = datos.condiciones[0]
    it = pp.l_cond.item(0)
    assert it.flags() & Qt.ItemIsEditable and it.checkState() == Qt.Checked
    it.setText("entrega   en bodega")                     # como si lo editara con doble clic
    app.processEvents()
    assert datos.condiciones[0] == "ENTREGA EN BODEGA" and original not in datos.condiciones
    assert "ENTREGA EN BODEGA" in pp.p.condiciones and original not in pp.p.condiciones
    assert type(datos)(datos.carpeta).condiciones[0] == "ENTREGA EN BODEGA"
    assert pp.l_cond.item(0).text() == "ENTREGA EN BODEGA"
    # repetido: no se acepta
    pp.l_cond.item(1).setText("ENTREGA EN BODEGA")
    app.processEvents()
    assert datos.condiciones.count("ENTREGA EN BODEGA") == 1 and len(datos.condiciones) == 2
    # la casilla marcada es verde y la vacía blanca
    for marcada, color in ((True, "#2e7d32"), (False, "#ffffff")):
        img = QImage(20, 20, QImage.Format_ARGB32)
        img.fill(QColor("#ffffff"))
        p = QPainter(img)
        pintar_casilla(p, QRectF(0, 0, 20, 20), marcada)
        p.end()
        assert img.pixelColor(5, 14).name() == color


def _pixel_pdf(pdf, x, y):
    """Color del punto (x, y) en fracciones de la página 1 del PDF."""
    from PySide6.QtCore import QSize
    from PySide6.QtPdf import QPdfDocument
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    doc = QPdfDocument()
    doc.load(str(pdf))
    img = doc.render(0, QSize(420, 594))
    from PySide6.QtGui import QColor, QImage, QPainter
    hoja = QImage(img.size(), QImage.Format_RGB32)              # papel blanco debajo
    hoja.fill(QColor("white"))
    pin = QPainter(hoja)
    pin.drawImage(0, 0, img)
    pin.end()
    return hoja.pixelColor(int(x * 419), int(y * 593))


def test_pdf_hoja_membretada_y_marca_de_agua(datos, tmp_path):
    from PySide6.QtGui import QColor, QImage
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    p = datos.nueva_proforma()
    p.items.append(datos.item_de(datos.modulos[0]))
    e = datos.empresa
    # logo rojo como marca de agua: el centro de la hoja queda rosado tenue; sin marca, blanco
    logo = QImage(200, 100, QImage.Format_RGB32)
    logo.fill(QColor("#ff0000"))
    logo.save(str(datos.fotos / "logo.png"))
    e.logo = "logo.png"
    sin = informes.pdf_cliente(p, datos, tmp_path / "sin.pdf")
    assert _pixel_pdf(sin, 0.5, 0.75).name() == "#ffffff"
    e.marca_agua, e.marca_agua_intensidad = True, 20
    con = informes.pdf_cliente(p, datos, tmp_path / "marca.pdf")
    c = _pixel_pdf(con, 0.5, 0.5)
    assert c.red() > 240 and 180 < c.green() < 230               # rojo al 20 %: rosado
    # tamaño del logo: chico (20 %) no llega a 0,3 del ancho; grande (100 %) sí
    e.marca_agua_tamano = 20
    assert _pixel_pdf(informes.pdf_cliente(p, datos, tmp_path / "chico.pdf"), 0.3, 0.5).name() == "#ffffff"
    e.marca_agua_tamano = 100
    assert _pixel_pdf(informes.pdf_cliente(p, datos, tmp_path / "grande.pdf"), 0.05, 0.5).name() != "#ffffff"
    # hoja membretada azul: cubre toda la hoja (esquinas incluidas) y reemplaza la marca de agua
    hoja = QImage(210, 297, QImage.Format_RGB32)
    hoja.fill(QColor("#0000ff"))
    hoja.save(str(datos.fotos / "membrete.png"))
    e.membrete, e.marca_agua_intensidad = "membrete.png", 100
    m = informes.pdf_cliente(p, datos, tmp_path / "membrete.pdf")
    for x, y in ((0.01, 0.01), (0.99, 0.99), (0.5, 0.97)):
        c = _pixel_pdf(m, x, y)
        assert c.blue() > 240 and c.red() < 15 and c.green() < 15
    assert "logo.png" not in informes.html_cliente(p, datos)      # el membrete ya trae el logo
    e.marca_agua_intensidad = 20                                  # la intensidad también aclara el membrete
    c = _pixel_pdf(informes.pdf_cliente(p, datos, tmp_path / "m20.pdf"), 0.99, 0.99)
    assert c.red() > 180 and c.blue() > 240


def test_empresa_membrete_desde_pdf(datos, tmp_path):
    from PySide6.QtGui import QColor, QPageSize, QPainter, QPdfWriter
    from PySide6.QtWidgets import QApplication, QFileDialog
    QApplication.instance() or QApplication([])
    from proformaapp.ui import ventana as v
    origen = tmp_path / "membrete.pdf"
    w = QPdfWriter(str(origen))
    w.setPageSize(QPageSize(QPageSize.A4))
    pin = QPainter(w)
    pin.fillRect(0, 0, 200, 200, QColor("#00aa00"))
    pin.end()
    ventana = v.VentanaPrincipal(datos)
    pe = ventana.pest_empresa
    import unittest.mock as um
    with um.patch.object(QFileDialog, "getOpenFileName", return_value=(str(origen), "")):
        pe.elegir_membrete()
    e = datos.empresa
    assert e.membrete.endswith(".png") and datos.ruta_foto(e.membrete)
    assert not pe.marca_agua.isEnabled() and pe.memb_sup.isEnabled() and pe.intensidad.isEnabled()
    assert e.marca_agua_intensidad == 100 and pe.intensidad.value() == 100
    pe.memb_sup.setValue(55)
    assert type(datos)(datos.carpeta).empresa.membrete_sup == 55
    assert not pe.tamano.isEnabled()
    pe.quitar_membrete()
    assert e.membrete == "" and pe.marca_agua.isEnabled() and pe.tamano.isEnabled()
    pe.tamano.setValue(45)
    assert pe.l_tamano.text() == "45 %" and type(datos)(datos.carpeta).empresa.marca_agua_tamano == 45


# --- arreglos de la auditoría -------------------------------------------------------------------
def _ventana(datos):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from proformaapp.ui.ventana import VentanaPrincipal
    return VentanaPrincipal(datos)


def _datos_con_modulo(tmp_path):
    d = Datos(tmp_path / "d")
    d.materiales += [Material("a", "MDF", 10.0), Material("b", "TORNILLO", 1.0)]
    d.modulos.append(Modulo("m1", "Mod", ancho=1.0, alto=2.0, receta={"a": 2, "b": 3}))
    d.guardar()
    return d


def test_archivo_danado_no_abre_ni_se_pisa(tmp_path):
    d = Datos(tmp_path)
    (tmp_path / "datos.json").write_text('{"version": 3, "materiales": [', encoding="utf-8")
    with pytest.raises(ValueError, match="respaldos"):
        Datos(tmp_path)
    assert (tmp_path / "datos.json").read_text(encoding="utf-8").endswith("[")
    assert d.materiales == []


def test_un_respaldo_por_dia_y_solo_siete(tmp_path):
    d = Datos(tmp_path)
    d.guardar()
    carpeta = tmp_path / "respaldos"
    carpeta.mkdir()
    for dia in range(1, 10):
        (carpeta / f"datos-2020-01-0{dia}.json").write_text("viejo")
    d.materiales.append(Material("a", "MDF", 1.0))
    d.guardar()
    hoy = sorted(carpeta.glob("datos-*.json"))[-1]
    assert len(list(carpeta.glob("datos-*.json"))) == 7 and "MDF" not in hoy.read_text(encoding="utf-8")
    d.guardar()                                         # otro guardado el mismo día no pisa la copia
    assert "MDF" not in hoy.read_text(encoding="utf-8")


def test_lo_no_guardado_no_llega_al_disco(tmp_path):
    d = _datos_con_modulo(tmp_path)
    p = d.nueva_proforma()
    p.margen = 25.0
    d.guardar_proforma(p)
    p.margen = 40.0
    d.guardar()
    assert Datos(tmp_path / "d").proformas[0].margen == 25.0


def test_preguntar_antes_de_perder_la_proforma(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    d = _datos_con_modulo(tmp_path)
    w = _ventana(d)
    pp = w.pest_proforma
    preguntas = []
    respuesta = QMessageBox.Cancel
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: preguntas.append(a[2]) or respuesta)
    pp.nueva()                                          # vacía: no hay nada que perder
    assert preguntas == []
    pp.p.items.append(d.item_de(d.modulos[0]))
    numero, p = pp.p.numero, pp.p
    pp.nueva()
    assert pp.p is p and len(preguntas) == 1            # Cancelar: sigue la misma
    assert not w.close() and w.pest_proforma.p is p     # tampoco cierra
    respuesta = QMessageBox.Save
    pp.nueva()
    assert d.proforma(p.id).numero == numero and pp.p is not p and len(preguntas) == 3
    preguntas.clear()
    assert w.close() and preguntas == []


def test_editar_modulo_respeta_medidas_de_la_proforma(tmp_path):
    d = _datos_con_modulo(tmp_path)
    w = _ventana(d)
    pp = w.pest_proforma
    pp.p.items.append(d.item_de(d.modulos[0]))
    pp.p.items[0].ancho, pp.p.items[0].nombre = 3.5, "Especial"
    w.pest_modulos.lista.setCurrentRow(0)
    w.pest_modulos.d_tipo.setText("Exhibidor")
    assert (pp.p.items[0].ancho, pp.p.items[0].nombre) == (3.5, "Especial")
    assert pp.p.items[0].descripcion == "Tipo: Exhibidor"
    w.close()


def test_avisa_al_borrar_material_en_uso(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    d = _datos_con_modulo(tmp_path)
    w = _ventana(d)
    t = w.pest_materiales.t
    fila = next(f for f in range(t.rowCount()) if t.item(f, 0).text() == "MDF")
    t.selectRow(fila)
    textos = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: textos.append(a[2]) or QMessageBox.No)
    w.pest_materiales.eliminar()
    assert "1 módulo(s)" in textos[0] and "Mod" in textos[0] and len(d.materiales) == 2


def test_pdf_que_no_se_puede_escribir_da_error(tmp_path):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    d = _datos_con_modulo(tmp_path)
    with pytest.raises(PermissionError):
        informes.pdf_cliente(d.nueva_proforma(), d, tmp_path / "no-existe" / "x.pdf")


def test_nota_de_credito_resta(tmp_path):
    xml = tmp_path / "nc.xml"
    xml.write_text("<notaCredito><infoTributaria><ruc>1790000000001</ruc></infoTributaria><infoNotaCredito>"
                   "<totalSinImpuestos>50.00</totalSinImpuestos><valorModificacion>50.00</valorModificacion>"
                   "</infoNotaCredito></notaCredito>")
    d = comprobantes.leer_xml(xml)
    assert (d["subtotal"], d["total"]) == (-50.0, -50.0) and str(d["iva"]) == "0.0"


def test_paquete_no_guarda_rutas_de_afuera(tmp_path):
    z = tmp_path / "p.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("x", "y")
    with zipfile.ZipFile(z) as f:
        assert paquete._extraer(f, "fotos", "../../victima.txt", tmp_path) == "victima.txt"
        assert paquete._extraer(f, "fotos", "..\\..\\victima.txt", tmp_path) == "victima.txt"
        assert paquete._extraer(f, "fotos", "C:victima.txt", tmp_path) == "victima.txt"
        assert paquete._extraer(f, "fotos", "../..", tmp_path) == ""


def test_numero_ocupado_recibe_el_siguiente(tmp_path):
    d = Datos(tmp_path)
    abierta = d.nueva_proforma()                        # abierta en blanco antes de importar un historial
    d.guardar_proforma(d.nueva_proforma())
    d.guardar_proforma(abierta)
    assert sorted(p.numero for p in d.proformas) == [1, 2] and abierta.numero == 2


def test_subtotal_es_la_suma_de_las_lineas():
    p = Proforma("x", 1, "2026-11-08", margen=0)
    p.adicionales = [Adicional("A", 1.25, 10.10), Adicional("B", 1.25, 10.10)]
    assert p.subtotal() == 25.26


def test_adicional_automatico_sigue_a_los_modulos(tmp_path):
    d = _datos_con_modulo(tmp_path)
    w = _ventana(d)
    pp, pa = w.pest_proforma, w.pest_adicionales
    pp.p.items.append(d.item_de(d.modulos[0]))
    pa.agregar({"descripcion": "LOGO", "costo": 75, "por": "modulos"})
    pp.p.items.append(d.item_de(d.modulos[0]))
    pp.recalcular()
    assert pp.p.adicionales[0].cantidad == 2
    pa.refrescar()
    pa.t.item(0, 1).setText("9")                        # a mano: deja de seguir a los módulos
    pp.p.items.append(d.item_de(d.modulos[0]))
    pp.recalcular()
    assert pp.p.adicionales[0].cantidad == 9
    w.close()


def test_leer_numero():
    from proformaapp.ui.comun import leer_numero
    for texto, valor in [("$ 1.234,50", 1234.5), ("1,5", 1.5), ("1.5", 1.5), ("1,234.56", 1234.56), ("1,125", 1.125),
                         ("-50,00", -50.0), ("abc", 7.0)]:
        assert leer_numero(texto, 7.0) == valor, texto


def test_importar_numeros_nombres_y_formulas(tmp_path):
    assert importar_mod._numero("12,50") == 12.5 and importar_mod._numero(0.125) == 0.125
    assert importar_mod._numero("2x4") == 0.0
    assert importar_mod._calcular("=9**9") is None and importar_mod._calcular("=2*3") == 6
    d = Datos(tmp_path / "a")
    d.materiales.append(Material("a", "DISEÑO 3D", 5.0))
    wb = Workbook()
    ws = wb.active
    ws.title = "RECETA"
    ws["A3"], ws["B3"] = "DISENO 3D", 9
    x = tmp_path / "x.xlsx"
    wb.save(x)
    assert importar_mod.importar(x, d)["materiales"] == 0 and len(d.materiales) == 1


def test_exportar_materiales_conserva_unidad_y_nombres_con_total(tmp_path):
    d = Datos(tmp_path / "a")
    d.materiales += [Material("a", "AAA", 1.0), Material("b", "TOTAL BOND", 2.0), Material("c", "ZZZ", 3.0, unidad="kg")]
    x = tmp_path / "m.xlsx"
    importar_mod.exportar_materiales(d, x)
    e = Datos(tmp_path / "b")
    importar_mod.importar(x, e)
    assert [(m.nombre, m.unidad) for m in e.materiales] == [("AAA", "u"), ("TOTAL BOND", "u"), ("ZZZ", "kg")]


def test_leer_iva():
    from proformaapp.modelo import iva_tasa, iva_texto, leer_iva
    for texto, codigo in [("13", "13"), ("12,5 %", "12.5"), ("IVA 15%", "15"), ("IVA 0% ARTESANO", "artesano"),
                          ("0", "0"), ("100", "100"), ("101", None), ("abc", None), ("-5", None), ("", None)]:
        assert leer_iva(texto) == codigo, texto
    assert iva_tasa("12.5") == 0.125 and iva_tasa("artesano") == 0.0 and iva_tasa("raro") == 0.0
    assert iva_texto("12.5") == "IVA 12,5%" and iva_texto("15") == "IVA 15%"


def test_iva_escrito_en_empresa_y_en_proforma(tmp_path):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    d = _datos_con_modulo(tmp_path)
    vieja = d.nueva_proforma()
    vieja.iva = "15"
    d.guardar_proforma(vieja)
    w = _ventana(d)

    def escribir(combo, texto):
        combo.lineEdit().clear()
        QTest.keyClicks(combo.lineEdit(), texto)
        QTest.keyClick(combo.lineEdit(), Qt.Key_Return)

    escribir(w.pest_empresa.iva, "13")
    assert d.empresa.iva == "13" and Datos(tmp_path / "d").empresa.iva == "13"
    escribir(w.pest_empresa.iva, "abc")                 # lo que no es un porcentaje se descarta
    assert d.empresa.iva == "13" and w.pest_empresa.iva.currentText() == "IVA 13%"

    pp = w.pest_proforma
    pp.nueva()
    assert pp.p.iva == "13" and pp.iva.currentText() == "IVA 13%"   # la proforma nueva toma el de la empresa
    pp.p.items.append(d.item_de(d.modulos[0]))                      # 23 de costo + 25 % = 28,75
    escribir(pp.iva, "12,5")
    assert pp.p.iva == "12.5" and pp.p.iva_valor() == 3.59 and pp.p.total() == 32.34
    assert "IVA 12,5%" in informes.html_cliente(pp.p, d)
    pp.guardar(silencioso=True)

    w.pest_historial.t.setCurrentCell(1, 0)
    pp.mostrar(d.proformas[0])
    assert pp.iva.currentText() == "IVA 15%"                        # la vieja conserva el suyo
    assert w.pest_empresa.iva.findData("13") >= 0
    assert set(Datos(tmp_path / "d").codigos_iva()) == {"artesano", "15", "13", "12.5"}   # queda para elegirlo otra vez
    w.close()


def test_iva_elegido_de_la_lista(tmp_path):
    d = _datos_con_modulo(tmp_path)
    w = _ventana(d)
    w.pest_proforma.iva.setCurrentIndex(w.pest_proforma.iva.findData("15"))
    assert w.pest_proforma.p.iva == "15" and w.pest_proforma.iva.currentText() == "IVA 15%"
    w.close()


def test_materiales_a_comprar_con_dos_precios(tmp_path):
    def receta(precio, cantidad):
        return [{"material": "a", "nombre": "MDF", "tipo": "material", "cantidad": cantidad, "precio": precio}]
    p = Proforma("i", 1, "2026-11-08", items=[Item("x", "A", receta=receta(10, 1)), Item("y", "B", receta=receta(12, 1)),
                                              Item("z", "C", cantidad=2, receta=receta(10, 3))])
    filas = p.materiales_consolidados()
    assert [(f["cantidad"], f["precio"], f["total"]) for f in filas] == [(7.0, 10, 70.0), (1.0, 12, 12.0)]
    assert sum(f["total"] for f in filas) == p.costo_total() == 82.0
    d = Datos(tmp_path / "d")
    x = informes.excel_costos(p, d, tmp_path / "c.xlsx")
    hoja = load_workbook(x)["Materiales a comprar"]
    assert [hoja.cell(f, 5).value for f in (4, 5)] == [70.0, 12.0] and hoja.cell(6, 1).value == "TOTAL MATERIALES Y SERVICIOS"
