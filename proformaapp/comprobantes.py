"""Lee facturas para cargarlas como gastos de un proyecto.

- XML del SRI (factura electrónica, autorizada o no): datos exactos.
- PDF (RIDE u otro): se extrae el texto y se buscan RUC, número, fecha, subtotal, IVA y total; el usuario los revisa
  antes de guardar.
"""

from __future__ import annotations

import datetime as dt
import re
import xml.etree.ElementTree as ET
from pathlib import Path


def _num(texto) -> float:
    """«1.234,56», «1,234.56», «1234.56» → 1234.56."""
    if texto is None:
        return 0.0
    t = re.sub(r"[^\d,.\-]", "", str(texto))
    if not t:
        return 0.0
    if "," in t and "." in t:
        if t.rfind(",") > t.rfind("."):
            t = t.replace(".", "").replace(",", ".")
        else:
            t = t.replace(",", "")
    elif "," in t:
        partes = t.split(",")
        t = t.replace(",", ".") if len(partes[-1]) in (1, 2) else t.replace(",", "")
    try:
        return round(float(t), 2)
    except ValueError:
        return 0.0


def _fecha_iso(texto: str) -> str:
    """«06/11/2026» o «2026-11-06» → «2026-11-06» (vacío si no se reconoce)."""
    texto = (texto or "").strip()
    for formato in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y"):
        try:
            return dt.datetime.strptime(texto[:10], formato).date().isoformat()
        except ValueError:
            continue
    return ""


def _sin_espacio_nombres(raiz: ET.Element) -> ET.Element:
    for e in raiz.iter():
        if isinstance(e.tag, str) and "}" in e.tag:
            e.tag = e.tag.split("}", 1)[1]
    return raiz


def leer_xml(ruta: Path) -> dict:
    """Factura electrónica del SRI → {proveedor, ruc, documento, fecha, subtotal, iva, total, descripcion}."""
    raiz = _sin_espacio_nombres(ET.fromstring(Path(ruta).read_bytes()))
    # archivo autorizado: <autorizacion><comprobante><![CDATA[<factura>…]]></comprobante></autorizacion>
    comp = raiz.find(".//comprobante")
    if comp is not None and comp.text and comp.text.strip().startswith("<"):
        raiz = _sin_espacio_nombres(ET.fromstring(comp.text.strip().encode("utf-8")))
    info_t = raiz.find(".//infoTributaria")
    if info_t is None:
        raise ValueError("El XML no parece una factura electrónica del SRI (no tiene «infoTributaria»).")

    def t(nodo, etiqueta):
        if nodo is None:
            return ""
        x = nodo.find(etiqueta)
        return (x.text or "").strip() if x is not None and x.text else ""

    info = next((n for n in (raiz.find(".//infoFactura"), raiz.find(".//infoNotaCredito"),
                             raiz.find(".//infoLiquidacionCompra")) if n is not None), None)
    documento = "-".join(x for x in (t(info_t, "estab"), t(info_t, "ptoEmi"), t(info_t, "secuencial")) if x)
    subtotal = _num(t(info, "totalSinImpuestos"))
    iva = 0.0
    if info is not None:
        for imp in info.iter("totalImpuesto"):
            if t(imp, "codigo") == "2":            # 2 = IVA
                iva += _num(t(imp, "valor"))
    total = _num(t(info, "importeTotal") or t(info, "valorModificacion")) or round(subtotal + iva, 2)
    if info is not None and info.tag == "infoNotaCredito":      # devuelve dinero: resta de lo gastado
        subtotal, iva, total = 0.0 - subtotal, 0.0 - iva, 0.0 - total
    detalles = [t(d, "descripcion") for d in raiz.iter("detalle") if t(d, "descripcion")]
    descripcion = "; ".join(detalles[:3]) + (f" (+{len(detalles) - 3} más)" if len(detalles) > 3 else "")
    return {"proveedor": t(info_t, "razonSocial") or t(info_t, "nombreComercial"), "ruc": t(info_t, "ruc"),
            "documento": documento, "fecha": _fecha_iso(t(info, "fechaEmision")), "subtotal": subtotal,
            "iva": round(iva, 2), "total": total, "descripcion": descripcion}


def texto_pdf(ruta: Path) -> str:
    """Texto de todas las páginas de un PDF (con QtPdf, que ya viene con PySide6).

    El texto de cada página puede no estar listo justo después de cargar el documento (QtPdf lo arma en
    segundo plano, sobre todo en Windows), así que se reintenta bombeando eventos hasta que aparezca.
    """
    from PySide6.QtCore import QCoreApplication, QEventLoop
    from PySide6.QtPdf import QPdfDocument

    doc = QPdfDocument()
    if doc.load(str(ruta)) != QPdfDocument.Error.None_:
        raise ValueError("No se pudo abrir el PDF (¿está dañado o protegido con contraseña?).")
    app = QCoreApplication.instance()
    partes = []
    for i in range(doc.pageCount()):
        texto = doc.getAllText(i).text()
        intentos = 0
        while not texto.strip() and app is not None and intentos < 25:
            app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
            texto = doc.getAllText(i).text()
            intentos += 1
        partes.append(texto)
    doc.close()
    return "\n".join(partes)


_MONTO = r"\$?\s*(-?\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{1,2})|-?\d+(?:[.,]\d{1,2})?)"


def _monto_tras(texto: str, etiquetas: list[str]) -> float:
    for e in etiquetas:
        m = re.search(e + r"[^\d\n$]{0,40}" + _MONTO, texto, re.I)
        if m:
            return _num(m.group(1))
    return 0.0


def datos_de_texto(texto: str) -> dict:
    """Busca en el texto de una factura (RIDE del SRI u otra) los datos principales. Lo que no encuentra queda
    vacío para que el usuario lo complete."""
    plano = re.sub(r"[ \t]+", " ", texto)
    ruc = re.search(r"R\.?\s*U\.?\s*C\.?\s*[:.]?\s*(\d{13})", plano, re.I) or re.search(r"\b(\d{13})\b", plano)
    documento = re.search(r"\b(\d{3}-\d{3}-\d{9})\b", plano)
    fecha = (re.search(r"FECHA\s*(?:DE)?\s*EMISI[OÓ]N\s*[:.]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})", plano, re.I) or
             re.search(r"\b(\d{2}/\d{2}/\d{4})\b", plano))
    subtotal = _monto_tras(plano, [r"SUBTOTAL\s+SIN\s+IMPUESTOS", r"SUBTOTAL\s+15\s*%", r"SUBTOTAL"])
    iva = _monto_tras(plano, [r"\bIVA\s*1[2-5]\s*%", r"\bIVA\b"])
    total = _monto_tras(plano, [r"VALOR\s+TOTAL", r"IMPORTE\s+TOTAL", r"TOTAL\s+A\s+PAGAR", r"\bTOTAL\b"])
    if not total and subtotal:
        total = round(subtotal + iva, 2)
    if not subtotal and total:
        subtotal = round(total - iva, 2)
    # el nombre del proveedor suele ser la primera línea con letras del documento
    proveedor = ""
    for linea in texto.splitlines():
        linea = linea.strip()
        if len(linea) > 3 and re.search(r"[A-Za-zÁÉÍÓÚÑ]{3}", linea) and not re.match(
                r"(R\.?U\.?C|FACTURA|NO\.?|N[ÚU]MERO|AUTORIZACI|AMBIENTE|EMISI|CLAVE|FECHA)", linea, re.I):
            proveedor = linea[:80]
            break
    return {"proveedor": proveedor, "ruc": ruc.group(1) if ruc else "",
            "documento": documento.group(1) if documento else "",
            "fecha": _fecha_iso(fecha.group(1)) if fecha else "", "subtotal": subtotal, "iva": iva, "total": total,
            "descripcion": ""}


def leer_pdf(ruta: Path) -> dict:
    return datos_de_texto(texto_pdf(ruta))
