"""Importa materiales, módulos (recetas), clientes y fotos desde el Excel de proformas del usuario.

Formato esperado (el del Excel «Proforma general»):
- Hoja RECETA: columna A los materiales y B su precio (filas 3 a 28); en la fila 1 el nombre de cada módulo y,
  debajo, en esa misma columna, la cantidad de cada material para un módulo.
- Hoja PROFORMA: módulos con descripción (C), medidas (D, E, F) y la fórmula del valor unitario (H) que
  apunta a la columna de la receta; fotos dibujadas en esas filas.
- Hojas de clientes: «CLIENTE :» en B1 y debajo RUC, dirección, contacto y correo (columna C).
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path, PurePosixPath

from openpyxl import load_workbook
from openpyxl.utils import column_index_from_string, get_column_letter

from .modelo import Cliente, Datos, Material, Modulo, nuevo_id, tipo_por_nombre


def _numero(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


_ARITMETICA = re.compile(r"^=\+?[\d.,\s+\-*/()]+$")


def _calcular(formula) -> float | None:
    """Resuelve fórmulas sencillas como «=0.6*2.44» o «=2.2+0.95» (cuando el Excel no guarda el resultado)."""
    if not isinstance(formula, str) or not _ARITMETICA.match(formula.replace(" ", "")):
        return None
    try:
        return float(eval(formula.lstrip("=+").replace(",", "."), {"__builtins__": {}}, {}))  # noqa: S307
    except (ArithmeticError, SyntaxError, ValueError, TypeError):
        return None


def _valor(hoja_valores, hoja_formulas, fila: int, col: int) -> float:
    v = hoja_valores.cell(fila, col).value
    if v is None and hoja_formulas is not None:
        calculado = _calcular(hoja_formulas.cell(fila, col).value)
        if calculado is not None:
            return calculado
    return _numero(v)


def _texto(v) -> str:
    return "" if v is None else str(v).replace("\xa0", " ").strip()


def _bonito(nombre: str) -> str:
    """«MODULO BANDEJERO FREGADERO 125» → «Módulo bandejero fregadero 125»."""
    t = nombre.strip().lower()
    t = re.sub(r"\bmodulo\b", "módulo", t)
    t = re.sub(r"\bmodulos\b", "módulos", t)
    return t[:1].upper() + t[1:]


def _unidad(nombre: str) -> str:
    n = nombre.upper()
    if n.startswith(("MDP", "HIGH GLOSS", "MDF", "TABLERO")):
        return "plancha"
    if n.startswith(("LAMINADO", "CD ", "TIRA", "PERFIL", "LED")):
        return "m"
    if n.startswith(("DISEÑO", "DISENO", "INVERSI")):
        return "m²"
    return "u"


def _fotos_por_fila(archivo: Path, hoja: str) -> dict[int, str]:
    """{fila: ruta interna de la imagen} de las imágenes ancladas en una hoja."""
    resultado = {}
    with zipfile.ZipFile(archivo) as z:
        nombres = set(z.namelist())
        libro = z.read("xl/workbook.xml").decode("utf-8", "replace")
        rels_libro = z.read("xl/_rels/workbook.xml.rels").decode("utf-8", "replace")
        m = re.search(r'<sheet [^>]*name="' + re.escape(hoja) + r'"[^>]*r:id="(rId\d+)"', libro)
        if not m:
            return {}
        destino = re.search(r'Id="' + m.group(1) + r'"[^>]*Target="([^"]+)"', rels_libro) or \
            re.search(r'Target="([^"]+)"[^>]*Id="' + m.group(1) + r'"', rels_libro)
        if not destino:
            return {}
        hoja_xml = str(PurePosixPath("xl") / destino.group(1).lstrip("/").removeprefix("xl/"))
        rels_hoja = str(PurePosixPath(hoja_xml).parent / "_rels" / (PurePosixPath(hoja_xml).name + ".rels"))
        if rels_hoja not in nombres:
            return {}
        dibujo = re.search(r'Target="([^"]*drawing\d+\.xml)"', z.read(rels_hoja).decode("utf-8", "replace"))
        if not dibujo:
            return {}
        dibujo_xml = str(PurePosixPath(hoja_xml).parent.joinpath(dibujo.group(1)))
        partes = []
        for p in dibujo_xml.split("/"):
            if p == "..":
                partes.pop()
            else:
                partes.append(p)
        dibujo_xml = "/".join(partes)
        rels_dibujo = str(PurePosixPath(dibujo_xml).parent / "_rels" / (PurePosixPath(dibujo_xml).name + ".rels"))
        if dibujo_xml not in nombres or rels_dibujo not in nombres:
            return {}
        x = z.read(dibujo_xml).decode("utf-8", "replace")
        rels = dict(re.findall(r'Id="(rId\d+)"[^>]*Target="\.\./media/([^"]+)"',
                               z.read(rels_dibujo).decode("utf-8", "replace")))
        for ancla in re.findall(r"<xdr:(?:twoCellAnchor|oneCellAnchor).*?</xdr:(?:twoCellAnchor|oneCellAnchor)>", x, re.S):
            fila = re.search(r"<xdr:from>.*?<xdr:row>(\d+)</xdr:row>", ancla, re.S)
            emb = re.search(r'r:embed="(rId\d+)"', ancla)
            if fila and emb and emb.group(1) in rels:
                resultado.setdefault(int(fila.group(1)) + 1, "xl/media/" + rels[emb.group(1)])
    return resultado


def importar(archivo: Path, datos: Datos) -> dict[str, int]:
    """Agrega a `datos` lo nuevo del Excel sin modificar lo que ya existe (se compara por nombre). Devuelve cuántos
    materiales, módulos, clientes y fotos se agregaron, y cuántos ya existían («sin_cambios»)."""
    archivo = Path(archivo)
    valores = load_workbook(archivo, data_only=True)
    formulas = load_workbook(archivo, data_only=False)
    if "RECETA" not in valores.sheetnames:
        raise ValueError("El Excel no tiene la hoja «RECETA» con los materiales y las recetas de los módulos.")
    rec = valores["RECETA"]
    rec_f = formulas["RECETA"]

    # --- materiales (columna A, precio en B, desde la fila 3 hasta «TOTAL») ---
    materiales: list[Material] = []
    fila_material: dict[int, Material] = {}
    for f in range(3, rec.max_row + 1):
        nombre = _texto(rec.cell(f, 1).value)
        if not nombre or nombre.upper().startswith("TOTAL"):
            if nombre:
                break
            continue
        tipo = tipo_por_nombre(nombre)
        m = Material(id=nuevo_id(), nombre=nombre, precio=_valor(rec, rec_f, f, 2), unidad=_unidad(nombre),
                     tipo=tipo)
        materiales.append(m)
        fila_material[f] = m

    # --- módulos: nombre en la fila 1 y «CANT» en la fila 2 de la misma columna ---
    modulos: list[Modulo] = []
    col_modulo: dict[int, Modulo] = {}
    for c in range(3, rec.max_column + 1):
        nombre = _texto(rec.cell(1, c).value)
        if not nombre.upper().startswith("MODULO") or _texto(rec.cell(2, c).value).upper() != "CANT":
            continue
        receta = {m.id: _valor(rec, rec_f, f, c) for f, m in fila_material.items()}
        mod = Modulo(id=nuevo_id(), nombre=_bonito(nombre), receta={k: v for k, v in receta.items() if v})
        modulos.append(mod)
        col_modulo[c] = mod

    # --- descripciones, medidas y fotos desde la hoja PROFORMA ---
    fotos = 0
    if "PROFORMA" in formulas.sheetnames:
        pf, pv = formulas["PROFORMA"], valores["PROFORMA"]
        imagenes = _fotos_por_fila(archivo, "PROFORMA")
        with zipfile.ZipFile(archivo) as z:
            for f in range(1, pf.max_row + 1):
                formula = _texto(pf.cell(f, 8).value)
                m = re.search(r"RECETA!\$?([A-Z]+)\$?\d+", formula)
                if not m:
                    continue
                mod = col_modulo.get(column_index_from_string(m.group(1)) - 1)
                if mod is None:
                    continue
                nombre = _texto(pv.cell(f, 1).value)
                if nombre:
                    mod.nombre = _bonito(nombre)
                mod.descripcion = _texto(pv.cell(f, 3).value) or _texto(pv.cell(f, 2).value)
                mod.ancho, mod.alto, mod.prof = (_valor(pv, pf, f, k) for k in (4, 5, 6))
                if f in imagenes:
                    interno = imagenes[f]
                    destino = datos.fotos / f"{mod.id}{PurePosixPath(interno).suffix.lower()}"
                    destino.write_bytes(z.read(interno))
                    mod.foto = destino.name
                    fotos += 1

    # --- clientes: hojas con «CLIENTE :» ---
    clientes: list[Cliente] = []
    for hoja in valores.worksheets:
        if not _texto(hoja.cell(1, 2).value).upper().startswith("CLIENTE"):
            continue
        campos = {}
        for f in range(1, 8):
            clave = _texto(hoja.cell(f, 2).value).upper().rstrip(" :")
            campos[clave] = _texto(hoja.cell(f, 3).value)
        nombre = campos.get("CLIENTE", "")
        if nombre and not any(c.nombre == nombre for c in clientes):
            clientes.append(Cliente(id=nuevo_id(), nombre=nombre, ruc=campos.get("RUC", ""),
                                    direccion=campos.get("DIRECCIÓN", campos.get("DIRECCION", "")),
                                    contacto=campos.get("CONTACTO", ""), correo=campos.get("CORREO", "")))

    # --- unir con lo que ya existe: lo que ya está (mismo nombre) NO se modifica; solo se agrega lo nuevo ---
    def clave(nombre: str) -> str:
        return " ".join(nombre.lower().split())

    existentes = {clave(m.nombre): m for m in datos.materiales}
    nuevos_mat, equivalente = [], {}
    for m in materiales:
        ya = existentes.get(clave(m.nombre))
        if ya is None:
            datos.materiales.append(m)
            existentes[clave(m.nombre)] = m
            nuevos_mat.append(m)
        else:
            equivalente[m.id] = ya.id        # las recetas nuevas usan el material que el usuario ya tenía
    mods_existentes = {clave(m.nombre) for m in datos.modulos}
    nuevos_mod = []
    for mod in modulos:
        if clave(mod.nombre) in mods_existentes:
            if mod.foto:                     # la foto extraída no se usa: se borra
                (datos.fotos / mod.foto).unlink(missing_ok=True)
                fotos -= 1
            continue
        mod.receta = {equivalente.get(k, k): v for k, v in mod.receta.items()}
        datos.modulos.append(mod)
        mods_existentes.add(clave(mod.nombre))
        nuevos_mod.append(mod)
    nuevos_cli = [c for c in clientes if not any(clave(x.nombre) == clave(c.nombre) for x in datos.clientes)]
    datos.clientes += nuevos_cli
    datos.guardar()
    return {"materiales": len(nuevos_mat), "modulos": len(nuevos_mod), "clientes": len(nuevos_cli), "fotos": fotos,
            "sin_cambios": (len(materiales) - len(nuevos_mat)) + (len(modulos) - len(nuevos_mod)) +
                           (len(clientes) - len(nuevos_cli))}


def letra(c: int) -> str:
    return get_column_letter(c)
