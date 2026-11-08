"""Datos del proformador (materiales, módulos con su receta, clientes, proformas) y cálculos de costo y precio."""

from __future__ import annotations

import copy
import datetime as dt
import json
import os
import re
import shutil
import unicodedata
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

# materiales que el usuario puede decidir no contar como costo en cada proforma
TIPO_MATERIAL = "material"
TIPO_DISENO = "diseno"
TIPO_INVERSION = "inversion"
# tipos opcionales: en cada proforma se decide si se cobran (casillas «Cobrar DISEÑO» / «Cobrar INVERSIÓN»)
OPCIONALES = [(TIPO_DISENO, "DISEÑO"), (TIPO_INVERSION, "INVERSIÓN")]


def tipo_por_nombre(nombre: str) -> str:
    n = nombre.upper()
    if n.startswith(("DISEÑO", "DISENO")):
        return TIPO_DISENO
    if n.startswith("INVERSI"):
        return TIPO_INVERSION
    return TIPO_MATERIAL

# el IVA se guarda como "artesano" o como su porcentaje ("15", "13", "12.5"): cada proforma conserva el suyo
IVAS = ["artesano", "15"]


def iva_tasa(codigo: str) -> float:
    try:
        return 0.0 if codigo == "artesano" else float(codigo) / 100
    except (TypeError, ValueError):
        return 0.0


def iva_texto(codigo: str) -> str:
    return "IVA 0% ARTESANO" if codigo == "artesano" else f"IVA {str(codigo).replace('.', ',')}%"


def leer_iva(texto: str) -> str | None:
    """Lo elegido o escrito («13», «12,5 %», «IVA 15%», «IVA 0% ARTESANO») → código; None si no es de 0 a 100 %."""
    if "artesano" in texto.lower():
        return "artesano"
    m = re.fullmatch(r"\s*(?:iva)?\s*(\d+(?:[.,]\d+)?)\s*%?\s*", texto, re.I)
    if not m:
        return None
    valor = round(float(m.group(1).replace(",", ".")), 2)
    return f"{valor:g}" if valor <= 100 else None

CONDICIONES = ["INCLUYE ENTREGA EN PUNTO DE VENTA", "1 AÑO DE GARANTÍA POR DEFECTOS DE FABRICACIÓN"]

# adicionales que se agregan con un clic; «por»: "modulos" (× número de módulos), "m2" (× metros cuadrados de la
# exhibición) o "uno"
PLANTILLAS = [
    {"descripcion": "LOGO", "costo": 75.0, "por": "modulos"},
    {"descripcion": "TRANSPORTE", "costo": 35.0, "por": "m2"},
    {"descripcion": "VIÁTICOS", "costo": 0.0, "por": "uno"},
]

CATEGORIAS_GASTO = ["MATERIALES", "TABLEROS", "HERRAJES", "LUCES", "ESTRUCTURA METÁLICA", "ACRÍLICOS",
                    "MANO DE OBRA", "TRANSPORTE", "VIÁTICOS", "OTROS"]
ESTADOS_GASTO = ["PAGADO", "PENDIENTE"]


def carpeta_datos() -> Path:
    base = Path(os.environ.get("PROFORMADOR_DATOS") or
                Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "proformador")
    base.mkdir(parents=True, exist_ok=True)
    return base


def redondear(x: float) -> float:
    return round(x + 1e-9, 2)


def nuevo_id() -> str:
    return uuid.uuid4().hex[:10]


@dataclass
class Material:
    id: str
    nombre: str
    precio: float
    unidad: str = "u"
    tipo: str = TIPO_MATERIAL


@dataclass
class Modulo:
    id: str
    nombre: str
    descripcion: str = ""
    ancho: float = 0.0
    alto: float = 0.0
    prof: float = 0.0
    foto: str = ""                                  # nombre del archivo en la carpeta de fotos
    receta: dict[str, float] = field(default_factory=dict)   # id de material → cantidad por módulo


@dataclass
class Cliente:
    id: str
    nombre: str
    ruc: str = ""
    direccion: str = ""
    contacto: str = ""
    correo: str = ""


@dataclass
class Empresa:
    id: str = ""
    nombre: str = ""
    ruc: str = ""
    direccion: str = ""
    telefono: str = ""
    correo: str = ""
    logo: str = ""
    margen: float = 25.0
    iva: str = "artesano"
    validez_dias: int = 15
    membrete: str = ""                # imagen de la hoja membretada (página A4 completa), en la carpeta de fotos
    membrete_sup: float = 40.0        # mm libres arriba y abajo para no tapar el encabezado/pie del membrete
    membrete_inf: float = 25.0
    marca_agua: bool = False          # sin membrete: el logo va de fondo, tenue, en cada página
    marca_agua_intensidad: float = 8.0   # % de opacidad
    marca_agua_tamano: float = 70.0      # % del ancho de la hoja que ocupa el logo de fondo


@dataclass
class Item:
    """Un módulo dentro de una proforma. Guarda una copia de la receta y los precios del momento, para que
    una proforma vieja no cambie si después se actualizan los precios."""
    modulo_id: str
    nombre: str
    cantidad: float = 1
    ancho: float = 0.0
    alto: float = 0.0
    prof: float = 0.0
    descripcion: str = ""
    foto: str = ""
    receta: list[dict] = field(default_factory=list)   # [{material, nombre, unidad, tipo, cantidad, precio}]

    def costo_unitario(self, no_cobrar=()) -> float:
        """Costo de un módulo; «no_cobrar» = tipos opcionales (diseño, inversión) que no se cobran."""
        return sum(r["cantidad"] * r["precio"] for r in self.receta if r.get("tipo") not in no_cobrar)

    @property
    def m2(self) -> float:
        return self.ancho * self.alto


@dataclass
class Adicional:
    """Otros costos de la proforma (logo, transporte, viáticos…): cantidad × costo unitario.
    Si «distribuir», no sale como línea aparte: su valor se reparte entre los módulos según el costo de cada uno."""
    descripcion: str
    cantidad: float = 1
    costo: float = 0.0
    distribuir: bool = False
    por: str = "uno"          # "modulos" o "m2": la cantidad sigue a los módulos; "uno": la cantidad es fija


@dataclass
class Gasto:
    """Un costo o gasto real de un proyecto (para comparar con lo que se cobró en la proforma)."""
    id: str
    proforma_id: str
    fecha: str = ""                 # aaaa-mm-dd
    proveedor: str = ""
    ruc: str = ""
    documento: str = ""             # n.º de factura (001-001-000000123)
    descripcion: str = ""
    categoria: str = "MATERIALES"
    subtotal: float = 0.0
    iva: float = 0.0
    total: float = 0.0
    estado: str = "PAGADO"
    archivo: str = ""               # copia del XML o PDF en la carpeta «comprobantes»
    origen: str = "manual"          # manual, xml o pdf


@dataclass
class Proforma:
    id: str
    numero: int
    fecha: str
    cliente_id: str = ""
    titulo: str = ""
    items: list[Item] = field(default_factory=list)
    adicionales: list[Adicional] = field(default_factory=list)
    no_cobrar: list[str] = field(default_factory=list)   # tipos opcionales (diseño, inversión) que NO se cobran
    margen: float = 25.0
    iva: str = "artesano"
    notas: str = ""
    imagen: str = ""          # foto o plano del diseño final (opcional), en la carpeta de fotos
    empresa_id: str = ""      # cuál de mis empresas emite la proforma
    condiciones: list[str] = field(default_factory=list)   # condiciones del servicio elegidas
    con_imagenes: bool = True  # el PDF lleva las fotos de los módulos y la imagen del diseño final

    # --- cálculos -------------------------------------------------------------------------
    @property
    def factor(self) -> float:
        return 1 + self.margen / 100

    def numero_modulos(self) -> float:
        return sum(i.cantidad for i in self.items)

    def m2_total(self) -> float:
        return sum(i.m2 * i.cantidad for i in self.items)

    def cantidad_por(self, por: str) -> float:
        """Cantidad de un adicional automático: número de módulos, m² de la exhibición o 1."""
        cantidad = self.numero_modulos() if por == "modulos" else self.m2_total() if por == "m2" else 1
        return redondear(cantidad or 1)

    def actualizar_adicionales(self) -> None:
        for a in self.adicionales:
            if a.por != "uno":
                a.cantidad = self.cantidad_por(a.por)

    def costo_items(self) -> float:
        return sum(i.costo_unitario(self.no_cobrar) * i.cantidad for i in self.items)

    def costo_adicionales(self) -> float:
        return sum(a.cantidad * a.costo for a in self.adicionales)

    def costo_total(self) -> float:
        return redondear(self.costo_items() + self.costo_adicionales())

    def adicionales_aparte(self) -> list[Adicional]:
        """Los adicionales que salen como línea propia en la proforma (los no distribuidos)."""
        return [a for a in self.adicionales if not a.distribuir]

    def total_distribuido(self) -> float:
        """Precio al cliente de los adicionales que se reparten entre los módulos."""
        return sum(self.precio_adicional(a) * a.cantidad for a in self.adicionales if a.distribuir)

    def reparto(self) -> list[tuple[Item, float, float]]:
        """[(ítem, porcentaje, monto)] de cómo se reparten los adicionales distribuidos: en proporción al precio
        de cada línea de módulos (precio unitario × cantidad, sin adicionales; si no hay precios, en proporción a la
        cantidad). Ej.: adicional de 100 y módulos de 60 y 40 → 60 y 40. Los montos van con 2 decimales y suman
        exactamente el total repartido (el centavo que sobra va a la línea más grande)."""
        pesos = [i.costo_unitario(self.no_cobrar) * self.factor * i.cantidad for i in self.items]
        if not sum(pesos):
            pesos = [i.cantidad for i in self.items]
        suma, total = sum(pesos), redondear(self.total_distribuido())
        if not suma:
            return [(i, 0.0, 0.0) for i in self.items]
        montos = [redondear(total * w / suma) for w in pesos]
        if montos:
            mayor = max(range(len(montos)), key=lambda k: pesos[k])
            montos[mayor] = redondear(montos[mayor] + total - sum(montos))
        return [(i, w / suma, m) for i, w, m in zip(self.items, pesos, montos)]

    def precio_unitario(self, item: Item) -> float:
        base = item.costo_unitario(self.no_cobrar) * self.factor
        if item.cantidad and any(a.distribuir for a in self.adicionales):
            base += next((monto for i, _p, monto in self.reparto() if i is item), 0.0) / item.cantidad
        return redondear(base)

    def precio_adicional(self, a: Adicional) -> float:
        return redondear(a.costo * self.factor)

    def subtotal(self) -> float:
        """Lo que paga el cliente antes de IVA (suma de las líneas ya redondeadas, como en la proforma)."""
        return redondear(sum(redondear(self.precio_unitario(i) * i.cantidad) for i in self.items) +
                         sum(redondear(self.precio_adicional(a) * a.cantidad) for a in self.adicionales_aparte()))

    def tasa_iva(self) -> float:
        return iva_tasa(self.iva)

    def texto_iva(self) -> str:
        return iva_texto(self.iva)

    def iva_valor(self) -> float:
        return redondear(self.subtotal() * self.tasa_iva())

    def total(self) -> float:
        return redondear(self.subtotal() + self.iva_valor())

    def ganancia(self) -> float:
        return redondear(self.subtotal() - self.costo_total())

    def materiales_consolidados(self) -> list[dict]:
        """Cuánto de cada material hace falta para toda la proforma (para comprar)."""
        total: dict[tuple, dict] = {}
        for i in self.items:
            for r in i.receta:
                if r.get("tipo") in self.no_cobrar:
                    continue
                # un mismo material puede tener dos precios si cambió entre un módulo y otro: va en filas separadas
                d = total.setdefault((r["material"], r["precio"]), {**r, "cantidad": 0.0})
                d["cantidad"] += r["cantidad"] * i.cantidad
        filas = [d for d in total.values() if d["cantidad"]]
        for d in filas:
            d["total"] = redondear(d["cantidad"] * d["precio"])
        return filas


# ---------------------------------------------------------------------------------------------
class Datos:
    """Todo lo que guarda el programa, en un archivo JSON en la carpeta de datos del usuario."""

    def __init__(self, carpeta: Path | None = None):
        self.carpeta = Path(carpeta or carpeta_datos())
        self.carpeta.mkdir(parents=True, exist_ok=True)
        self.fotos = self.carpeta / "fotos"
        self.fotos.mkdir(exist_ok=True)
        self.comprobantes = self.carpeta / "comprobantes"
        self.comprobantes.mkdir(exist_ok=True)
        self.empresas: list[Empresa] = []
        self.empresa_activa = ""
        self.tema = "claro"                                    # estilo de la pantalla
        self.condiciones: list[str] = list(CONDICIONES)        # catálogo de condiciones del servicio
        self.plantillas: list[dict] = [dict(p) for p in PLANTILLAS]
        self.gastos: list[Gasto] = []
        self.materiales: list[Material] = []
        self.modulos: list[Modulo] = []
        self.clientes: list[Cliente] = []
        self.proformas: list[Proforma] = []
        self.cargar()

    @property
    def archivo(self) -> Path:
        return self.carpeta / "datos.json"

    # --- mis empresas -------------------------------------------------------------------------
    @property
    def empresa(self) -> Empresa:
        """La empresa elegida en «Datos de mi empresa» (se usa por defecto en las proformas nuevas)."""
        if not self.empresas:
            self.empresas.append(Empresa(id=nuevo_id()))
        return next((e for e in self.empresas if e.id == self.empresa_activa), self.empresas[0])

    def codigos_iva(self) -> list[str]:
        """Los IVA de la lista: los de siempre y los ya usados (un IVA de feriado queda para elegirlo otra vez)."""
        return list(dict.fromkeys([*IVAS, *(e.iva for e in self.empresas), *(p.iva for p in self.proformas)]))

    def empresa_de(self, proforma: Proforma) -> Empresa:
        return next((e for e in self.empresas if e.id == proforma.empresa_id), self.empresa)

    def cargar(self) -> None:
        try:
            d = json.loads(self.archivo.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, ValueError) as e:      # abrir vacío haría que el próximo guardado borre los datos
            raise ValueError(f"No se pudo leer {self.archivo} ({e}). No se cambió nada; en la carpeta «respaldos», "
                             "junto a ese archivo, hay copias de días anteriores.") from e
        version = d.get("version", 1)
        self.tema = d.get("tema", "claro")
        campos = Empresa.__annotations__
        if "empresas" in d:
            self.empresas = [Empresa(**{k: v for k, v in e.items() if k in campos}) for e in d["empresas"]]
            self.empresa_activa = d.get("empresa_activa", "")
            self.condiciones = list(d.get("condiciones", CONDICIONES))
            self.plantillas = list(d.get("plantillas", PLANTILLAS))
        else:                              # versión 2 o anterior: una sola empresa con sus condiciones
            vieja = dict(d.get("empresa", {}))
            self.condiciones = list(vieja.get("condiciones", CONDICIONES))
            self.plantillas = list(vieja.get("plantillas", PLANTILLAS))
            e = Empresa(**{k: v for k, v in vieja.items() if k in campos})
            e.id = e.id or nuevo_id()
            self.empresas, self.empresa_activa = [e], e.id
        if version < 2:                    # antes DISEÑO e INVERSIÓN eran un solo tipo
            for m in d.get("materiales", []):
                if m.get("tipo") == TIPO_DISENO and tipo_por_nombre(m["nombre"]) == TIPO_INVERSION:
                    m["tipo"] = TIPO_INVERSION
            for p in d.get("proformas", []):
                for i in p.get("items", []):
                    for r in i.get("receta", []):
                        if r.get("tipo") == TIPO_DISENO and tipo_por_nombre(r["nombre"]) == TIPO_INVERSION:
                            r["tipo"] = TIPO_INVERSION
        self.materiales = [Material(**m) for m in d.get("materiales", [])]
        self.modulos = [Modulo(**m) for m in d.get("modulos", [])]
        self.clientes = [Cliente(**c) for c in d.get("clientes", [])]
        self.proformas = []
        for p in d.get("proformas", []):
            p = dict(p)
            if version < 3:                # antes salían siempre todas las condiciones de la empresa
                p.setdefault("empresa_id", self.empresa_activa)
                p.setdefault("condiciones", list(self.condiciones))
            p["items"] = [Item(**i) for i in p.get("items", [])]
            p["adicionales"] = [Adicional(**a) for a in p.get("adicionales", [])]
            # formatos anteriores: una casilla para los dos juntos, o una lista de materiales excluidos
            if p.pop("incluir_diseno", True) is False:
                p.setdefault("no_cobrar", [TIPO_DISENO, TIPO_INVERSION])
            excluidos = p.pop("excluidos", [])
            if excluidos and "no_cobrar" not in p:
                p["no_cobrar"] = sorted({r.get("tipo") for i in p["items"] for r in i.receta
                                         if r["material"] in excluidos} - {TIPO_MATERIAL})
            self.proformas.append(Proforma(**p))
        self.gastos = [Gasto(**g) for g in d.get("gastos", [])]

    def guardar(self) -> None:
        datos = {"version": 3, "tema": self.tema, "empresas": [asdict(e) for e in self.empresas],
                 "empresa_activa": self.empresa_activa, "condiciones": self.condiciones,
                 "plantillas": self.plantillas,
                 "materiales": [asdict(m) for m in self.materiales],
                 "modulos": [asdict(m) for m in self.modulos],
                 "clientes": [asdict(c) for c in self.clientes],
                 "proformas": [asdict(p) for p in self.proformas],
                 "gastos": [asdict(g) for g in self.gastos]}
        temporal = self.archivo.with_suffix(".tmp")
        temporal.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
        # se guarda en cada tecla: una copia por día, de los últimos 7, para que el respaldo sirva de algo
        respaldo = self.carpeta / "respaldos" / f"datos-{dt.date.today().isoformat()}.json"
        if self.archivo.exists() and not respaldo.exists():
            respaldo.parent.mkdir(exist_ok=True)
            shutil.copy2(self.archivo, respaldo)
            for viejo in sorted(respaldo.parent.glob("datos-*.json"))[:-7]:
                viejo.unlink()
        os.replace(temporal, self.archivo)

    # --- búsquedas ------------------------------------------------------------------------
    def material(self, id_: str) -> Material | None:
        return next((m for m in self.materiales if m.id == id_), None)

    def modulo(self, id_: str) -> Modulo | None:
        return next((m for m in self.modulos if m.id == id_), None)

    def cliente(self, id_: str) -> Cliente | None:
        return next((c for c in self.clientes if c.id == id_), None)

    def proforma(self, id_: str) -> Proforma | None:
        return next((p for p in self.proformas if p.id == id_), None)

    def gastos_de(self, proforma_id: str) -> list[Gasto]:
        return [g for g in self.gastos if g.proforma_id == proforma_id]

    def ruta_foto(self, nombre: str) -> Path | None:
        if not nombre:
            return None
        p = self.fotos / nombre
        return p if p.is_file() else None

    def costo_modulo(self, modulo: Modulo, no_cobrar=()) -> float:
        total = 0.0
        for mid, cant in modulo.receta.items():
            m = self.material(mid)
            if m and m.tipo not in no_cobrar:
                total += cant * m.precio
        return total

    # --- armar una proforma -----------------------------------------------------------------
    def nueva_proforma(self) -> Proforma:
        numero = max((p.numero for p in self.proformas), default=0) + 1
        e = self.empresa
        return Proforma(id=nuevo_id(), numero=numero, fecha=dt.date.today().isoformat(), margen=e.margen,
                        iva=e.iva, empresa_id=e.id, condiciones=list(self.condiciones))

    def item_de(self, modulo: Modulo, cantidad: float = 1) -> Item:
        receta = []
        for mid, cant in modulo.receta.items():
            m = self.material(mid)
            if m is not None and cant:
                receta.append(self.linea_receta(m, cant))
        return Item(modulo_id=modulo.id, nombre=modulo.nombre, cantidad=cantidad, ancho=modulo.ancho,
                    alto=modulo.alto, prof=modulo.prof, descripcion=modulo.descripcion, foto=modulo.foto,
                    receta=receta)

    @staticmethod
    def linea_receta(m: Material, cantidad: float = 1) -> dict:
        """Una fila de receta (copia del precio actual del material)."""
        return {"material": m.id, "nombre": m.nombre, "unidad": m.unidad, "tipo": m.tipo,
                "cantidad": cantidad, "precio": m.precio}

    def guardar_como_modulo(self, item: Item, modulo_id: str = "") -> Modulo:
        """Guarda la receta de un ítem de la proforma en el catálogo de módulos (nuevo o reemplazando uno)."""
        receta: dict[str, float] = {}
        for r in item.receta:
            receta[r["material"]] = receta.get(r["material"], 0) + r["cantidad"]
        mod = self.modulo(modulo_id) if modulo_id else None
        if mod is None:
            mod = Modulo(id=nuevo_id(), nombre=item.nombre)
            self.modulos.append(mod)
        mod.nombre, mod.descripcion, mod.receta = item.nombre, item.descripcion, receta
        mod.ancho, mod.alto, mod.prof = item.ancho, item.alto, item.prof
        if item.foto:
            mod.foto = item.foto
        item.modulo_id = mod.id
        self.guardar()
        return mod

    def actualizar_precios(self, proforma: Proforma) -> None:
        """Pone los precios actuales de los materiales en la receta de cada módulo (para una proforma copiada).
        La receta (qué materiales y cuánto) se respeta tal como se armó."""
        for item in proforma.items:
            for r in item.receta:
                m = self.material(r["material"])
                if m is not None:
                    r.update(nombre=m.nombre, unidad=m.unidad, tipo=m.tipo, precio=m.precio)

    def guardar_proforma(self, proforma: Proforma) -> None:
        """Guarda una copia: lo que se siga editando en pantalla no cambia la proforma guardada."""
        for i, p in enumerate(self.proformas):
            if p.id == proforma.id:
                self.proformas[i] = copy.deepcopy(proforma)
                break
        else:
            if any(p.numero == proforma.numero for p in self.proformas):     # p. ej., se importó un historial
                proforma.numero = max(p.numero for p in self.proformas) + 1
            self.proformas.append(copy.deepcopy(proforma))
        self.guardar()


# --- descripción estándar de un módulo -------------------------------------------------------
CAMPOS_DESCRIPCION = ("Tipo", "Materiales de fabricación", "Característica específica")


def sin_tildes(texto: str) -> str:
    """Minúsculas y sin tildes, para buscar «diseno» y encontrar «DISEÑO»."""
    return "".join(c for c in unicodedata.normalize("NFKD", (texto or "").lower()) if not unicodedata.combining(c))


def clave_nombre(texto: str) -> str:
    """Para saber si dos nombres son el mismo: sin tildes, mayúsculas ni espacios de más."""
    return " ".join(sin_tildes(texto).split())


def _campo_de_linea(linea: str) -> tuple[int, str] | None:
    """Si la línea empieza con «Tipo:», «Materiales de fabricación:»… devuelve (n.º de campo, resto)."""
    plano = sin_tildes(linea.strip())
    for n, campo in enumerate(CAMPOS_DESCRIPCION):
        if plano.startswith(sin_tildes(campo) + ":"):
            return n, linea.strip()[len(campo) + 1:].strip()
    return None


def separar_descripcion(texto: str) -> list[str]:
    """Texto guardado → [tipo, materiales, característica]. Un texto viejo sin etiquetas va a «Característica»."""
    partes: list[list[str]] = [[], [], []]
    actual = 2
    for linea in (texto or "").splitlines():
        campo = _campo_de_linea(linea)
        if campo is not None:
            actual, resto = campo
            if resto:
                partes[actual].append(resto)
        else:
            partes[actual].append(linea)
    return ["\n".join(p).strip() for p in partes]


def unir_descripcion(tipo: str, materiales: str, caracteristica: str) -> str:
    """[tipo, materiales, característica] → texto con etiquetas (se omiten los campos vacíos)."""
    lineas = []
    for campo, valor in zip(CAMPOS_DESCRIPCION, (tipo, materiales, caracteristica)):
        valor = (valor or "").strip()
        if not valor:
            continue
        if "\n" in valor:
            lineas.append(f"{campo}:\n{valor}")
        else:
            lineas.append(f"{campo}: {valor}")
    return "\n".join(lineas)
