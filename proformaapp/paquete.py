"""Pasar módulos y el historial de proformas de una PC a otra: un archivo .zip con los datos (JSON) y sus
archivos (fotos, logos, comprobantes).

- Módulos: lleva cada módulo con su receta y los materiales que usa. Al importar, un material que ya existe con el
  mismo nombre se reutiliza (no se cambia su precio); los que faltan se agregan.
- Historial: lleva las proformas con sus clientes, empresas emisoras y gastos. Los clientes y empresas se
  reconocen por nombre o RUC; si el N.º de una proforma ya está ocupado por otra, recibe el siguiente N.º libre.

En ambos casos, lo que ya existe (módulo con el mismo nombre, proforma con el mismo id) se reemplaza solo si se
pide; si no, se deja como está.
"""

from __future__ import annotations

import json
import unicodedata
import zipfile
from dataclasses import asdict, fields
from pathlib import Path, PurePosixPath

from .modelo import Adicional, Cliente, Datos, Empresa, Gasto, Item, Material, Modulo, Proforma, nuevo_id

FORMATO = "proformador-paquete"
VERSION = 1


def _clave(texto: str) -> str:
    t = unicodedata.normalize("NFD", texto or "")
    return " ".join("".join(c for c in t if unicodedata.category(c) != "Mn").lower().split())


def _crear(cls, d: dict):
    """Instancia un dataclass ignorando campos desconocidos (paquetes de versiones más nuevas)."""
    nombres = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in d.items() if k in nombres})


# --- escribir / leer el zip --------------------------------------------------------------------
def _escribir(archivo: Path, tipo: str, contenido: dict, adjuntos: list[tuple[Path, str]]) -> None:
    archivo = Path(archivo)
    temporal = archivo.with_name(archivo.name + ".tmp")
    with zipfile.ZipFile(temporal, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("contenido.json", json.dumps({"formato": FORMATO, "version": VERSION, "tipo": tipo,
                                                 **contenido}, ensure_ascii=False, indent=1))
        vistos = set()
        for origen, destino in adjuntos:
            if destino not in vistos and origen.is_file():
                z.write(origen, destino)
                vistos.add(destino)
    temporal.replace(archivo)


def _leer(archivo: Path, tipo: str) -> tuple[dict, zipfile.ZipFile]:
    try:
        z = zipfile.ZipFile(archivo)
        d = json.loads(z.read("contenido.json").decode("utf-8"))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile) as e:
        raise ValueError("El archivo no es un paquete del Proformador Ágil.") from e
    if d.get("formato") != FORMATO:
        z.close()
        raise ValueError("El archivo no es un paquete del Proformador Ágil.")
    if d.get("tipo") != tipo:
        z.close()
        otro = {"modulos": "de MÓDULOS", "historial": "del HISTORIAL"}.get(d.get("tipo"), "de otro tipo")
        raise ValueError(f"Este paquete es {otro}; impórtelo desde esa pestaña.")
    return d, z


def _extraer(z: zipfile.ZipFile, carpeta_zip: str, nombre: str, destino: Path) -> str:
    """Copia carpeta_zip/nombre a la carpeta destino (sin pisar un archivo distinto) y devuelve el nombre final."""
    if not nombre:
        return ""
    ruta = f"{carpeta_zip}/{nombre}"
    if ruta not in z.namelist():
        return nombre
    datos = z.read(ruta)
    nombre = PurePosixPath(nombre).name                    # nunca rutas fuera de la carpeta
    final = destino / nombre
    if final.exists() and final.read_bytes() != datos:
        final = destino / f"{final.stem}-{nuevo_id()[:4]}{final.suffix}"
    if not final.exists():
        final.write_bytes(datos)
    return final.name


# --- módulos ---------------------------------------------------------------------------------
def exportar_modulos(datos: Datos, archivo: Path) -> int:
    usados = {mid for m in datos.modulos for mid in m.receta}
    materiales = [asdict(m) for m in datos.materiales if m.id in usados]
    adjuntos = [(datos.fotos / m.foto, f"fotos/{m.foto}") for m in datos.modulos if m.foto]
    _escribir(archivo, "modulos", {"materiales": materiales, "modulos": [asdict(m) for m in datos.modulos]},
              adjuntos)
    return len(datos.modulos)


def modulos_repetidos(datos: Datos, archivo: Path) -> list[str]:
    """Nombres de los módulos del paquete que ya existen aquí (para preguntar si se reemplazan)."""
    d, z = _leer(archivo, "modulos")
    z.close()
    aqui = {_clave(m.nombre) for m in datos.modulos}
    return [m["nombre"] for m in d.get("modulos", []) if _clave(m["nombre"]) in aqui]


def importar_modulos(datos: Datos, archivo: Path, reemplazar: bool = False) -> dict[str, int]:
    d, z = _leer(archivo, "modulos")
    r = {"modulos": 0, "reemplazados": 0, "omitidos": 0, "materiales": 0}
    with z:
        # materiales: por nombre; los que faltan se agregan
        por_nombre = {_clave(m.nombre): m for m in datos.materiales}
        ids = {m.id for m in datos.materiales}
        mapa: dict[str, str] = {}
        for md in d.get("materiales", []):
            existente = por_nombre.get(_clave(md["nombre"]))
            if existente is None:
                mat = _crear(Material, md)
                if mat.id in ids:
                    mat.id = nuevo_id()
                datos.materiales.append(mat)
                por_nombre[_clave(mat.nombre)], existente = mat, mat
                ids.add(mat.id)
                r["materiales"] += 1
            mapa[md["id"]] = existente.id
        # módulos: por nombre
        mods = {_clave(m.nombre): m for m in datos.modulos}
        ids_mod = {m.id for m in datos.modulos}
        for mdd in d.get("modulos", []):
            nuevo = _crear(Modulo, mdd)
            nuevo.receta = {mapa[mid]: c for mid, c in nuevo.receta.items() if mid in mapa}
            nuevo.foto = _extraer(z, "fotos", nuevo.foto, datos.fotos)
            viejo = mods.get(_clave(nuevo.nombre))
            if viejo is not None:
                if not reemplazar:
                    r["omitidos"] += 1
                    continue
                nuevo.id = viejo.id                        # las proformas siguen apuntando al mismo módulo
                datos.modulos[datos.modulos.index(viejo)] = nuevo
                r["reemplazados"] += 1
            else:
                if nuevo.id in ids_mod:
                    nuevo.id = nuevo_id()
                datos.modulos.append(nuevo)
                r["modulos"] += 1
            mods[_clave(nuevo.nombre)] = nuevo
            ids_mod.add(nuevo.id)
    datos.guardar()
    return r


# --- historial --------------------------------------------------------------------------------
def exportar_historial(datos: Datos, archivo: Path) -> int:
    ids_cli = {p.cliente_id for p in datos.proformas}
    ids_emp = {p.empresa_id for p in datos.proformas}
    ids_pro = {p.id for p in datos.proformas}
    empresas = [e for e in datos.empresas if e.id in ids_emp]
    gastos = [g for g in datos.gastos if g.proforma_id in ids_pro]
    adjuntos = [(datos.fotos / x, f"fotos/{x}") for e in empresas for x in (e.logo, e.membrete) if x]
    for p in datos.proformas:
        if p.imagen:
            adjuntos.append((datos.fotos / p.imagen, f"fotos/{p.imagen}"))
        adjuntos += [(datos.fotos / i.foto, f"fotos/{i.foto}") for i in p.items if i.foto]
    adjuntos += [(datos.comprobantes / g.archivo, f"comprobantes/{g.archivo}") for g in gastos if g.archivo]
    _escribir(archivo, "historial", {
        "proformas": [asdict(p) for p in datos.proformas],
        "clientes": [asdict(c) for c in datos.clientes if c.id in ids_cli],
        "empresas": [asdict(e) for e in empresas],
        "gastos": [asdict(g) for g in gastos]}, adjuntos)
    return len(datos.proformas)


def proformas_repetidas(datos: Datos, archivo: Path) -> list[int]:
    """N.º de las proformas del paquete que ya están aquí (mismo id)."""
    d, z = _leer(archivo, "historial")
    z.close()
    aqui = {p.id for p in datos.proformas}
    return [p["numero"] for p in d.get("proformas", []) if p["id"] in aqui]


def _buscar(lista, d: dict):
    """Cliente o empresa igual: mismo id, o mismo RUC, o mismo nombre."""
    for x in lista:
        if x.id == d.get("id"):
            return x
    ruc = (d.get("ruc") or "").strip()
    for x in lista:
        if ruc and x.ruc.strip() == ruc:
            return x
    for x in lista:
        if _clave(x.nombre) and _clave(x.nombre) == _clave(d.get("nombre", "")):
            return x
    return None


def importar_historial(datos: Datos, archivo: Path, reemplazar: bool = False) -> dict[str, int]:
    d, z = _leer(archivo, "historial")
    r = {"proformas": 0, "reemplazadas": 0, "omitidas": 0, "renumeradas": 0, "clientes": 0, "empresas": 0,
         "gastos": 0}
    with z:
        cli: dict[str, str] = {}
        for cd in d.get("clientes", []):
            x = _buscar(datos.clientes, cd)
            if x is None:
                x = _crear(Cliente, cd)
                datos.clientes.append(x)
                r["clientes"] += 1
            cli[cd["id"]] = x.id
        emp: dict[str, str] = {}
        for ed in d.get("empresas", []):
            x = _buscar(datos.empresas, ed)
            if x is None:
                x = _crear(Empresa, ed)
                x.id = x.id or nuevo_id()
                x.logo = _extraer(z, "fotos", x.logo, datos.fotos)
                x.membrete = _extraer(z, "fotos", x.membrete, datos.fotos)
                datos.empresas.append(x)
                r["empresas"] += 1
            emp[ed["id"]] = x.id
        gastos_de: dict[str, list[dict]] = {}
        for gd in d.get("gastos", []):
            gastos_de.setdefault(gd["proforma_id"], []).append(gd)

        for pd in sorted(d.get("proformas", []), key=lambda p: p["numero"]):
            pd = dict(pd)
            pd["items"] = [_crear(Item, i) for i in pd.get("items", [])]
            pd["adicionales"] = [_crear(Adicional, a) for a in pd.get("adicionales", [])]
            p = _crear(Proforma, pd)
            viejo = datos.proforma(p.id)
            if viejo is not None and not reemplazar:
                r["omitidas"] += 1
                continue
            p.cliente_id = cli.get(p.cliente_id, p.cliente_id)
            p.empresa_id = emp.get(p.empresa_id, p.empresa_id)
            p.imagen = _extraer(z, "fotos", p.imagen, datos.fotos)
            for i in p.items:
                i.foto = _extraer(z, "fotos", i.foto, datos.fotos)
            if viejo is not None:
                p.numero = viejo.numero
                datos.proformas[datos.proformas.index(viejo)] = p
                datos.gastos = [g for g in datos.gastos if g.proforma_id != p.id]
                r["reemplazadas"] += 1
            else:
                if any(x.numero == p.numero for x in datos.proformas):
                    p.numero = max(x.numero for x in datos.proformas) + 1
                    r["renumeradas"] += 1
                datos.proformas.append(p)
                r["proformas"] += 1
            ids_g = {g.id for g in datos.gastos}
            for gd in gastos_de.get(p.id, []):
                g = _crear(Gasto, gd)
                if g.id in ids_g:
                    g.id = nuevo_id()
                g.archivo = _extraer(z, "comprobantes", g.archivo, datos.comprobantes)
                datos.gastos.append(g)
                r["gastos"] += 1
        # PC recién instalada: la empresa en blanco que se crea sola sobra si llegaron empresas de verdad
        usadas = {p.empresa_id for p in datos.proformas}
        vacias = [e for e in datos.empresas if not e.nombre.strip() and not e.ruc.strip() and e.id not in usadas]
        if r["empresas"] and len(vacias) < len(datos.empresas):
            datos.empresas = [e for e in datos.empresas if e not in vacias]
            if datos.empresa_activa not in {e.id for e in datos.empresas}:
                datos.empresa_activa = datos.empresas[0].id
    datos.guardar()
    return r
