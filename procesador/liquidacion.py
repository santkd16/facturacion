from __future__ import annotations

from decimal import Decimal
from typing import Dict, Iterable, List, Optional, Tuple

from .models import CuentaContableProveedor, Proveedor

CASILLAS = [
    "SUBTOTAL",
    "IVA",
    "INC",
    "RETEFUENTE",
    "RETEICA",
    "RETEIVA",
    "TOTAL_NETO",
]

RETENCIONES = {"RETEFUENTE", "RETEICA", "RETEIVA"}

CASILLA_FIELD_MAP = {
    "SUBTOTAL": "subtotal",
    "IVA": "iva",
    "INC": "inc",
    "RETEFUENTE": "retefuente",
    "RETEICA": "reteica",
    "RETEIVA": "reteiva",
    "TOTAL_NETO": "total_neto",
}

CATALOGO_RESPONSE_KEYS = {
    "SUBTOTAL": "subtotales",
    "IVA": "iva",
    "INC": "inc",
    "RETEFUENTE": "retefuente",
    "RETEICA": "reteica",
    "RETEIVA": "reteiva",
    "TOTAL_NETO": "totalneto",
}

CASILLA_RULES = {
    "SUBTOTAL": {
        "prefijos": ("2310", "2432","N/A","na","BSP","bsp"),
        "excluir": ("231053152007",),
        "mensaje_sin_opciones": "No hay opciones disponibles para esta casilla; parametrice el proveedor.",
        "naturaleza": "D",
    },
    "IVA": {
        "prefijos": ("2408","N/A","na","BSP","bsp"),
        "mensaje_sin_opciones": "No hay opciones disponibles para esta casilla; parametrice el proveedor.",
        "naturaleza": "D",
    },
    "INC": {
        "prefijos": ("231053152007","N/A","na","BSP","bsp"),
        "mensaje_sin_opciones": "No hay opciones disponibles para esta casilla; parametrice el proveedor.",
        "naturaleza": "D",
    },
    "RETEFUENTE": {
        "prefijos": ("2365","N/A","na","BSP","bsp"),
        "mensaje_sin_opciones": "El proveedor no tiene parametrizadas opciones para ReteFuente.",
        "naturaleza": "C",
    },
    "RETEICA": {
        "prefijos": ("2368","N/A","na","BSP","bsp"),
        "mensaje_sin_opciones": "El proveedor no tiene parametrizadas opciones para esta retención.",
        "naturaleza": "C",
    },
    "RETEIVA": {
        "prefijos": ("2367","N/A","na","BSP","bsp"),
        "mensaje_sin_opciones": "El proveedor no tiene parametrizadas opciones para esta retención.",
        "naturaleza": "C",
    },
    "TOTAL_NETO": {
        "prefijos": ("2335","N/A","na","BSP","bsp"),
        "mensaje_sin_opciones": "No hay opciones disponibles para esta casilla; parametrice el proveedor.",
        "naturaleza": "D",
    },
}

CASILLA_HELP_TEXT = {
    "SUBTOTAL": "2310% (excepto 231053152007) o 2432%.",
    "IVA": "2408%.",
    "INC": "Solo 231053152007.",
    "RETEFUENTE": "2365% parametrizada por proveedor.",
    "RETEICA": "2368% parametrizada (porcentaje o por-mil).",
    "RETEIVA": "2367% parametrizada.",
    "TOTAL_NETO": "2335%.",
}


def es_cuenta_inc_exclusiva(codigo: str) -> bool:
    return codigo == "231053152007"


def validar_prefijo_para_casilla(casilla: str, codigo: str) -> Optional[str]:
    if not codigo:
        # Sin cuenta seleccionada, no hay nada que validar
        return None

    reglas = CASILLA_RULES[casilla]

    # === CASILLA INC ===
    # Para INC queremos permitir:
    # - La cuenta exclusiva 231053152007
    # - La "cuenta" N/A (cuando no aplica INC)
    if casilla == "INC":
        if codigo == "231053152007":
            return None
        if codigo.upper() in {"N/A", "NA","BSP","bsp"}:
            return None
        # Cualquier otra cosa en INC es error
        return "La cuenta 231053152007 es exclusiva de INC."

    # === OTRAS CASILLAS (no INC) ===

    # La cuenta exclusiva de INC NO se puede usar en otras casillas
    if es_cuenta_inc_exclusiva(codigo) and casilla != "INC":
        return "La cuenta 231053152007 es exclusiva de INC."

    # Exclusiones específicas por casilla (por si las configuras en CASILLA_RULES)
    if "excluir" in reglas and codigo in reglas["excluir"]:
        return "La cuenta seleccionada no corresponde a la casilla esperada."

    # Validación por prefijo
    prefijos = reglas.get("prefijos", ())
    if prefijos and not any(codigo.startswith(pref) for pref in prefijos):
        return "La cuenta seleccionada no corresponde a la casilla esperada."

    # Todo OK
    return None



def agrupar_catalogos_por_proveedor(
    proveedor_ids: Iterable[int],
    *,
    empresa_id: Optional[int] = None,
) -> Tuple[
    Dict[int, Proveedor],
    Dict[Tuple[int, str], List[CuentaContableProveedor]],
    Dict[int, CuentaContableProveedor],
]:
    filtro = {"id__in": proveedor_ids}
    if empresa_id is not None:
        filtro["empresa_id"] = empresa_id

    proveedores = {p.id: p for p in Proveedor.objects.filter(**filtro)}

    catalogos = (
        CuentaContableProveedor.objects.filter(
            proveedor_id__in=proveedores.keys(), activo=True
        )
        .select_related("cuenta", "proveedor")
        .order_by("casilla", "cuenta__codigo")
    )

    catalogos_por_clave: Dict[Tuple[int, str], List[CuentaContableProveedor]] = {}
    catalogos_por_id: Dict[int, CuentaContableProveedor] = {}
    for item in catalogos:
        catalogos_por_id[item.id] = item
        catalogos_por_clave.setdefault((item.proveedor_id, item.casilla), []).append(
            item
        )

    return proveedores, catalogos_por_clave, catalogos_por_id


def calcular_retencion(
    base: Decimal,
    catalogo: CuentaContableProveedor,
) -> Tuple[Decimal, Decimal]:
    porcentaje = catalogo.porcentaje or Decimal("0")
    modo = catalogo.modo_calculo or CuentaContableProveedor.ModoCalculo.PORCENTAJE
    if modo == CuentaContableProveedor.ModoCalculo.PORMIL:
        valor = (base * porcentaje) / Decimal("1000")
    else:
        valor = (base * porcentaje) / Decimal("100")
    return porcentaje, valor


def signo_por_naturaleza(naturaleza: str) -> Decimal:
    return Decimal("1") if naturaleza == "D" else Decimal("-1")
