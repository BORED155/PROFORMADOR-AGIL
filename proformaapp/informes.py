"""Los dos informes: la proforma para el cliente (PDF) y el informe de costos para usted (Excel)."""

from __future__ import annotations

import datetime as dt
import html
from pathlib import Path

from .modelo import CAMPOS_DESCRIPCION, OPCIONALES, Datos, Proforma, _campo_de_linea, redondear

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
         "noviembre", "diciembre"]


def _linea_descripcion(linea: str) -> str:
    """Una línea de la descripción para el PDF; las etiquetas estándar («Tipo:»…) van en negrita."""
    linea = linea.strip()
    campo = _campo_de_linea(linea)
    if campo is None:
        return html.escape(linea)
    n, resto = campo
    return f"<b>{html.escape(CAMPOS_DESCRIPCION[n])}:</b> {html.escape(resto)}".rstrip()


def dinero(x: float) -> str:
    return "$ " + f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def numero(x: float) -> str:
    """Cantidad o medida con 2 decimales y coma decimal (1,50)."""
    return f"{x:.2f}".replace(".", ",")


def medida(x: float) -> str:
    return numero(x) if x else ""


def fecha_larga(iso: str) -> str:
    try:
        d = dt.date.fromisoformat(iso)
    except ValueError:
        return iso
    return f"{d.day} de {MESES[d.month - 1]} de {d.year}"


def fecha_corta(iso: str) -> str:
    """«2026-11-06» → «06/11/2026»."""
    try:
        return dt.date.fromisoformat(iso).strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return iso or ""


def nombre_archivo(proforma: Proforma, datos: Datos, sufijo: str, extension: str) -> str:
    cliente = datos.cliente(proforma.cliente_id)
    base = f"Proforma {proforma.numero:04d}"
    if cliente:
        base += f" - {cliente.nombre}"
    base += f" - {sufijo}{extension}"
    return "".join(c for c in base if c not in '\\/:*?"<>|')


# ---------------------------------------------------------------------------------------------
# PDF para el cliente
# ---------------------------------------------------------------------------------------------
def html_cliente(proforma: Proforma, datos: Datos) -> str:
    e, c = datos.empresa_de(proforma), datos.cliente(proforma.cliente_id)
    esc = html.escape
    logo = datos.ruta_foto(e.logo)
    cab_empresa = ""
    if datos.ruta_foto(e.membrete):
        logo = None                    # la hoja membretada ya trae logo y datos de la empresa
    if logo:
        cab_empresa += f'<img src="{logo.as_uri()}" height="140"><br>'
    if e.nombre:
        cab_empresa += f'<span style="font-size:15pt; font-weight:bold; color:#0d47a1">{esc(e.nombre)}</span><br>'
    detalles = [x for x in (f"RUC: {e.ruc}" if e.ruc else "", e.direccion, e.telefono, e.correo) if x]
    cab_empresa += "<br>".join(esc(x) for x in detalles)
    if datos.ruta_foto(e.membrete):
        cab_empresa = ""

    cliente_html = ""
    if c:
        for etiqueta, valor in (("CLIENTE", c.nombre), ("RUC", c.ruc), ("DIRECCIÓN", c.direccion),
                                ("CONTACTO", c.contacto), ("CORREO", c.correo)):
            if valor:
                cliente_html += (f'<tr><td style="color:#546e7a; padding-right:8px"><b>{etiqueta}:</b></td>'
                                 f'<td>{esc(valor)}</td></tr>')

    filas = ""
    for n, i in enumerate(proforma.items, 1):
        foto = datos.ruta_foto(i.foto) if proforma.con_imagenes else None
        img = f'<img src="{foto.as_uri()}" width="120">' if foto else ""
        desc = "<br>".join(_linea_descripcion(l) for l in i.descripcion.splitlines() if l.strip())
        medidas = " × ".join(medida(x) for x in (i.ancho, i.alto, i.prof) if x)
        pu = proforma.precio_unitario(i)
        filas += f"""
        <tr>
          <td align="center" valign="top">{n}</td>
          <td valign="top"><b>{esc(i.nombre.upper())}</b><br><span style="font-size:8pt">{desc}</span></td>
          {f'<td align="center" valign="top">{img}</td>' if proforma.con_imagenes else ''}
          <td align="center" valign="top">{medidas + ' m' if medidas else ''}</td>
          <td align="center" valign="top">{numero(i.cantidad)}</td>
          <td align="right" valign="top">{dinero(pu)}</td>
          <td align="right" valign="top"><b>{dinero(redondear(pu * i.cantidad))}</b></td>
        </tr>"""
    for a in proforma.adicionales_aparte():
        if not a.cantidad or not a.costo:
            continue
        pu = proforma.precio_adicional(a)
        filas += f"""
        <tr>
          <td></td><td colspan="{3 if proforma.con_imagenes else 2}"><b>{esc(a.descripcion.upper())}</b></td>
          <td align="center">{numero(a.cantidad)}</td>
          <td align="right">{dinero(pu)}</td>
          <td align="right"><b>{dinero(redondear(pu * a.cantidad))}</b></td>
        </tr>"""

    imagen_final = ""
    final = datos.ruta_foto(proforma.imagen) if proforma.con_imagenes else None
    if final:
        imagen_final = (f'<p style="margin-top:12px"><b>DISEÑO FINAL</b></p>'
                        f'<p align="center"><img src="{final.as_uri()}" width="640"></p>')
    condiciones = "".join(f"<li>{esc(x)}</li>" for x in proforma.condiciones if x.strip())
    validez = (f"<li>PROFORMA VÁLIDA POR {e.validez_dias} DÍAS</li>" if e.validez_dias else "")
    notas = "<p>" + "<br>".join(esc(x) for x in proforma.notas.splitlines()) + "</p>" if proforma.notas.strip() else ""
    iva = (f'<tr><td align="right">{esc(proforma.texto_iva())}</td>'
           f'<td align="right" width="120">{dinero(proforma.iva_valor())}</td></tr>')
    return f"""
<html><body style="font-family: 'DejaVu Sans', Arial, sans-serif; font-size: 9pt; color:#212121">
<table width="100%"><tr>
  <td valign="top">{cab_empresa}</td>
  <td valign="top" align="right">
    <span style="font-size:20pt; font-weight:bold; color:#0d47a1">PROFORMA</span><br>
    <b>N.º {proforma.numero:04d}</b><br>{fecha_larga(proforma.fecha)}
  </td>
</tr></table>
<hr>
<table cellspacing="0" cellpadding="2">{cliente_html}</table>
<p style="font-size:12pt; font-weight:bold; color:#0d47a1; margin-top:10px">{esc(proforma.titulo.upper())}</p>
<table width="100%" cellspacing="0" cellpadding="5" border="1" style="border-collapse:collapse; border-color:#b0bec5">
  <tr style="background-color:#0d47a1; color:white">
    <th width="4%">#</th><th width="{34 if proforma.con_imagenes else 52}%">TIPO DE EXHIBIDOR Y DESCRIPCIÓN</th>
    {'<th width="18%">FOTO REFERENCIAL</th>' if proforma.con_imagenes else ''}
    <th width="12%">MEDIDAS<br>(ancho × alto × prof.)</th><th width="7%">CANT.</th>
    <th width="12%">VALOR UNITARIO</th><th width="13%">VALOR TOTAL</th>
  </tr>
  {filas}
</table>
<table width="100%" cellspacing="0" cellpadding="4" style="margin-top:6px">
  <tr><td width="60%"></td><td>
    <table width="100%" cellspacing="0" cellpadding="4">
      <tr><td align="right">SUBTOTAL</td><td align="right" width="120">{dinero(proforma.subtotal())}</td></tr>
      {iva}
      <tr style="background-color:#e3f2fd"><td align="right"><b>VALOR TOTAL</b></td>
          <td align="right"><b style="font-size:11pt">{dinero(proforma.total())}</b></td></tr>
    </table>
  </td></tr>
</table>
{notas}
{imagen_final}
<p style="margin-top:14px"><b>CONDICIONES DEL SERVICIO:</b></p>
<ul>{condiciones}{validez}</ul>
</body></html>"""


MM_A4 = (210.0, 297.0)
MARGEN_MM = 14.0


def pdf_cliente(proforma: Proforma, datos: Datos, destino: Path) -> Path:
    """PDF A4. Fondo de cada página: la hoja membretada de la empresa (estirada a toda la hoja) o, si no tiene y
    lo pidió, su logo como marca de agua tenue en el centro."""
    from PySide6.QtCore import QMarginsF, QRectF, QSizeF
    from PySide6.QtGui import QImage, QPageLayout, QPageSize, QPainter, QPdfWriter, QTextDocument

    destino = Path(destino)
    e = datos.empresa_de(proforma)
    dpi = 150
    escritor = QPdfWriter(str(destino))
    escritor.setPageSize(QPageSize(QPageSize.A4))
    escritor.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Millimeter)
    escritor.setResolution(dpi)
    escritor.setTitle(f"Proforma {proforma.numero:04d}")
    escritor.setCreator(e.nombre or "Proformador")

    def px(mm: float) -> float:
        return mm / 25.4 * dpi

    pagina = QRectF(0, 0, px(MM_A4[0]), px(MM_A4[1]))
    membrete = datos.ruta_foto(e.membrete)
    fondo = None
    opacidad = max(1.0, min(100.0, e.marca_agua_intensidad)) / 100     # vale para el membrete y para el logo
    arriba = abajo = MARGEN_MM
    if membrete:
        fondo = QImage(str(membrete))
        arriba, abajo = max(5.0, e.membrete_sup), max(5.0, e.membrete_inf)
    elif e.marca_agua and datos.ruta_foto(e.logo):
        fondo = QImage(str(datos.ruta_foto(e.logo)))
    if fondo is not None and fondo.isNull():
        fondo = None

    contenido = QRectF(px(MARGEN_MM), px(arriba), pagina.width() - 2 * px(MARGEN_MM),
                       pagina.height() - px(arriba) - px(abajo))
    doc = QTextDocument()
    doc.setDocumentMargin(0)
    doc.setHtml(html_cliente(proforma, datos))
    doc.setPageSize(QSizeF(contenido.width(), contenido.height()))

    p = QPainter(escritor)
    for n in range(max(1, doc.pageCount())):
        if n:
            escritor.newPage()
        if fondo is not None:
            p.save()
            p.setOpacity(opacidad)
            if membrete:
                destino_fondo = pagina                           # la hoja membretada ocupa toda la página
            else:                                                # el logo: centrado, 70 % del ancho
                w = pagina.width() * 0.7
                h = w * fondo.height() / fondo.width()
                if h > pagina.height() * 0.6:
                    h = pagina.height() * 0.6
                    w = h * fondo.width() / fondo.height()
                destino_fondo = QRectF(0, 0, w, h)
                destino_fondo.moveCenter(pagina.center())
            p.drawImage(destino_fondo, fondo)
            p.restore()
        p.save()
        p.translate(contenido.left(), contenido.top() - n * contenido.height())
        doc.drawContents(p, QRectF(0, n * contenido.height(), contenido.width(), contenido.height()))
        p.restore()
    p.end()
    return destino


# ---------------------------------------------------------------------------------------------
# Excel de costos (para usted)
# ---------------------------------------------------------------------------------------------
def excel_costos(proforma: Proforma, datos: Datos, destino: Path) -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    destino = Path(destino)
    libro = Workbook()
    azul = PatternFill("solid", fgColor="0D47A1")
    gris = PatternFill("solid", fgColor="ECEFF1")
    verde = PatternFill("solid", fgColor="E8F5E9")
    blanca = Font(bold=True, color="FFFFFF")
    negrita = Font(bold=True)
    fino = Side(style="thin", color="B0BEC5")
    borde = Border(top=fino, bottom=fino, left=fino, right=fino)
    dinero_fmt = '"$" #,##0.00'
    cliente = datos.cliente(proforma.cliente_id)

    def cabecera(hoja, fila, titulos):
        for j, t in enumerate(titulos, 1):
            c = hoja.cell(fila, j, t)
            c.fill, c.font, c.border = azul, blanca, borde
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    def anchos(hoja, valores):
        for j, w in enumerate(valores, 1):
            hoja.column_dimensions[get_column_letter(j)].width = w

    # --- Resumen ---
    h = libro.active
    h.title = "Resumen"
    h["A1"] = f"INFORME DE COSTOS — PROFORMA N.º {proforma.numero:04d}"
    h["A1"].font = Font(bold=True, size=14, color="0D47A1")
    h["A2"] = f"{cliente.nombre if cliente else ''} — {proforma.titulo}".strip(" —")
    no_cobrados = [n for t, n in OPCIONALES if t in proforma.no_cobrar]
    h["A3"] = f"Fecha: {fecha_larga(proforma.fecha)}   ·   Ganancia: {numero(proforma.margen)} % sobre el costo" + \
        (f"   ·   No se cobran: {', '.join(no_cobrados)}" if no_cobrados else "")
    cabecera(h, 5, ["Módulo / adicional", "Cant.", "Costo unitario", "Costo total", "Precio unitario (cliente)",
                    "Precio total (cliente)", "Ganancia"])
    f = 6
    for i in proforma.items:
        cu = i.costo_unitario(proforma.no_cobrar)
        pu = proforma.precio_unitario(i)
        h.append([i.nombre, i.cantidad, cu, cu * i.cantidad, pu, pu * i.cantidad, pu * i.cantidad - cu * i.cantidad])
        f += 1
    for a in proforma.adicionales:
        if not a.cantidad or not a.costo:
            continue
        if a.distribuir:          # su precio ya está dentro de los módulos
            h.append([f"{a.descripcion} (repartido en los módulos)", a.cantidad, a.costo, a.costo * a.cantidad,
                      None, 0, -a.costo * a.cantidad])
        else:
            pu = proforma.precio_adicional(a)
            h.append([a.descripcion, a.cantidad, a.costo, a.costo * a.cantidad, pu, pu * a.cantidad,
                      (pu - a.costo) * a.cantidad])
        f += 1
    ultima = f - 1
    h.append(["TOTAL", None, None, f"=SUM(D6:D{ultima})", None, f"=SUM(F6:F{ultima})", f"=SUM(G6:G{ultima})"])
    for c in h[f]:
        c.font, c.fill = negrita, gris
    for fila in h.iter_rows(min_row=6, max_row=f):
        for c in fila:
            c.border = borde
            if c.column >= 3:
                c.number_format = dinero_fmt
    f += 2
    resumen = [("Lo que le cuesta a usted (costo)", proforma.costo_total()),
               ("Lo que paga el cliente (sin IVA)", proforma.subtotal()),
               (proforma.texto_iva(), proforma.iva_valor()),
               ("Lo que paga el cliente (total)", proforma.total()),
               ("Su ganancia", proforma.ganancia())]
    for texto, valor in resumen:
        h.cell(f, 1, texto).font = negrita
        c = h.cell(f, 4, valor)
        c.number_format, c.font = dinero_fmt, negrita
        if texto == "Su ganancia":
            for col in range(1, 5):
                h.cell(f, col).fill = verde
        f += 1
    if proforma.costo_total():
        h.cell(f, 1, "Ganancia sobre el precio de venta")
        h.cell(f, 4, proforma.ganancia() / proforma.subtotal() if proforma.subtotal() else 0).number_format = "0.00%"
    anchos(h, [44, 8, 16, 16, 20, 20, 16])

    # --- Materiales a comprar ---
    m = libro.create_sheet("Materiales a comprar")
    m["A1"] = "MATERIALES PARA TODA LA PROFORMA"
    m["A1"].font = Font(bold=True, size=13, color="0D47A1")
    cabecera(m, 3, ["Material", "Unidad", "Cantidad", "Precio unitario", "Total"])
    filas = proforma.materiales_consolidados()
    for d in filas:
        m.append([d["nombre"], d.get("unidad", ""), d["cantidad"], d["precio"], d["total"]])
    total_f = 4 + len(filas)
    m.append(["TOTAL MATERIALES Y SERVICIOS", None, None, None, f"=SUM(E4:E{total_f - 1})"])
    for c in m[total_f]:
        c.font, c.fill = negrita, gris
    for fila in m.iter_rows(min_row=4, max_row=total_f):
        for c in fila:
            c.border = borde
            if c.column >= 4:
                c.number_format = dinero_fmt
    anchos(m, [34, 10, 12, 16, 16])

    # --- Detalle por módulo ---
    d = libro.create_sheet("Detalle por módulo")
    f = 1
    for i in proforma.items:
        d.cell(f, 1, f"{i.nombre}  (× {numero(i.cantidad)})").font = Font(bold=True, size=12, color="0D47A1")
        f += 1
        cabecera(d, f, ["Material", "Unidad", "Cant. por módulo", "Precio unitario", "Costo por módulo",
                        "Cant. total", "Costo total"])
        f += 1
        inicio = f
        for r in i.receta:
            if r.get("tipo") in proforma.no_cobrar:
                continue
            d.append([r["nombre"], r.get("unidad", ""), r["cantidad"], r["precio"], r["cantidad"] * r["precio"],
                      r["cantidad"] * i.cantidad, r["cantidad"] * r["precio"] * i.cantidad])
            f += 1
        d.append(["COSTO DEL MÓDULO", None, None, None, f"=SUM(E{inicio}:E{f - 1})", None,
                  f"=SUM(G{inicio}:G{f - 1})"])
        for c in d[f]:
            c.font, c.fill = negrita, gris
        for fila in d.iter_rows(min_row=inicio, max_row=f):
            for c in fila:
                c.border = borde
                if c.column in (4, 5, 7):
                    c.number_format = dinero_fmt
        f += 2
    anchos(d, [34, 10, 16, 16, 18, 12, 16])

    # --- Gastos reales del proyecto (si ya se cargaron) ---
    gastos = sorted(datos.gastos_de(proforma.id), key=lambda g: g.fecha)
    if gastos:
        g = libro.create_sheet("Gastos reales")
        g["A1"] = "COSTOS Y GASTOS REALES DEL PROYECTO"
        g["A1"].font = Font(bold=True, size=13, color="0D47A1")
        cabecera(g, 3, ["Fecha", "Proveedor", "Documento", "Descripción", "Categoría", "Subtotal", "IVA", "Total",
                        "Estado"])
        for x in gastos:
            g.append([fecha_corta(x.fecha), x.proveedor, x.documento, x.descripcion, x.categoria, x.subtotal, x.iva,
                      x.total, x.estado])
        ft = 4 + len(gastos)
        g.append(["TOTAL GASTADO", None, None, None, None, f"=SUM(F4:F{ft - 1})", f"=SUM(G4:G{ft - 1})",
                  f"=SUM(H4:H{ft - 1})"])
        for c in g[ft]:
            c.font, c.fill = negrita, gris
        for fila in g.iter_rows(min_row=4, max_row=ft):
            for c in fila:
                c.border = borde
                if 6 <= c.column <= 8:
                    c.number_format = dinero_fmt
        g.cell(ft + 2, 1, "Contrato (paga el cliente)").font = negrita
        g.cell(ft + 2, 8, proforma.total()).number_format = dinero_fmt
        g.cell(ft + 3, 1, "Ganancia / pérdida real").font = negrita
        c = g.cell(ft + 3, 8, f"=H{ft + 2}-H{ft}")
        c.number_format, c.font = dinero_fmt, negrita
        anchos(g, [12, 30, 20, 34, 18, 14, 12, 14, 12])

    # todo número sin formato propio (cantidades, precios) se muestra con 2 decimales
    for hoja in libro.worksheets:
        for fila in hoja.iter_rows():
            for c in fila:
                if c.number_format == "General" and (isinstance(c.value, (int, float)) and not isinstance(c.value, bool)
                                                     or isinstance(c.value, str) and c.value.startswith("=")):
                    c.number_format = "#,##0.00"
    libro.save(destino)
    return destino
