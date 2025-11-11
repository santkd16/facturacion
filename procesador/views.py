from __future__ import annotations
import json
import os
import tempfile
import zipfile
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import xml.etree.ElementTree as ET
import pandas as pd
from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.db import connection
from django.db.utils import DatabaseError, ProgrammingError
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_GET, require_POST

NATURALEZA_ERROR_MSG = "La naturaleza de la cuenta seleccionada no coincide con la casilla esperada."
CUENTA_PROVEEDOR_MSG = "La cuenta seleccionada no pertenece al proveedor de la factura."
CASILLA_ERROR_MSG = "La cuenta seleccionada no corresponde a la casilla esperada."
CAMPO_OBLIGATORIO_MSG = "El campo ‘Cuenta contable’ es obligatorio porque el importe es distinto de cero."


from .forms import UploadExcelForm, UploadZipForm
from .models import (
    CuentaContableProveedor,
    Empresa,
    FacturaXML,
    FacturaXLS,
    PermisoEmpresa,
    Proveedor,
)
from .liquidacion import (
    CASILLAS,
    CASILLA_FIELD_MAP,
    CASILLA_HELP_TEXT,
    CASILLA_RULES,
    CATALOGO_RESPONSE_KEYS,
    RETENCIONES,
    agrupar_catalogos_por_proveedor,
    calcular_retencion,
    signo_por_naturaleza,
    validar_prefijo_para_casilla,
)

# Namespaces for XML UBL
ns = {
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
}


def _find_text(element, path, *, required: bool = False, default=None):
    node = element.find(path, ns)
    if node is not None and node.text is not None:
        return node.text.strip()
    if required:
        raise ValueError(f"El nodo requerido '{path}' no se encontró en el XML")
    return default


def _parse_decimal(value, default: Decimal = Decimal("0")) -> Decimal:
    if value is None:
        return default
    cleaned = str(value).strip().replace("$", "")
    if not cleaned:
        return default
    # convert decimal with comma as decimal separator
    if cleaned.count(",") == 1 and cleaned.count(".") == 0:
        cleaned = cleaned.replace(",", ".")
    else:
        cleaned = cleaned.replace(",", "")
    try:
        return Decimal(cleaned)
    except (InvalidOperation, TypeError):
        return default


def _decimal_to_str(value: Decimal, places: int = 2) -> str:
    if not isinstance(value, Decimal):
        value = _parse_decimal(value)
    quantum = Decimal(1).scaleb(-places)
    return f"{value.quantize(quantum, rounding=ROUND_HALF_UP)}"


def _coerce_fecha(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, pd.Timestamp):
        if pd.isna(value):
            return None
        return value.date()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            return None
        parsed = parse_date(cleaned)
        if parsed is not None:
            return parsed
        try:
            ts = pd.to_datetime(cleaned, errors="coerce")
        except Exception:
            ts = pd.NaT
        if not pd.isna(ts):
            return ts.date()
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            ts = pd.to_datetime(value, errors="coerce")
        except Exception:
            ts = pd.NaT
        if not pd.isna(ts):
            return ts.date()
    return None


def _extract_fecha_xls(row) -> date | None:
    """Intenta obtener la fecha del documento desde una fila de Excel."""

    keys: list[str] = []
    if hasattr(row, "index"):
        keys = [k for k in row.index if isinstance(k, str)]
    elif isinstance(row, dict):
        keys = [k for k in row.keys() if isinstance(k, str)]

    for key in keys:
        if "fecha" not in key.lower():
            continue
        value = row.get(key)
        fecha = _coerce_fecha(value)
        if fecha is not None:
            return fecha
    return None


def ensure_fecha_documento_column() -> None:
    """Garantiza que la columna ``fecha_documento`` exista antes de usarla."""

    tabla = FacturaXLS._meta.db_table
    try:
        with connection.cursor() as cursor:
            descripcion = connection.introspection.get_table_description(
                cursor, tabla
            )
    except (ProgrammingError, DatabaseError):  # pragma: no cover
        return

    if any(col.name == "fecha_documento" for col in descripcion):
        return

    from django.db import models

    campo = models.DateField(blank=True, null=True)
    campo.set_attributes_from_name("fecha_documento")
    try:
        with connection.schema_editor() as editor:
            editor.add_field(FacturaXLS, campo)
    except Exception:
        # Si otro proceso ya la creó evitamos propagar el error.
        return


def sincronizar_estado_facturas_xls(empresa: Empresa):
    xml_cufes = set(
        FacturaXML.objects.filter(empresa=empresa).values_list("cufe", flat=True)
    )
    actualizar = []
    for f in FacturaXLS.objects.filter(empresa=empresa).only("id", "cufe", "activo"):
        activo = f.cufe in xml_cufes
        if f.activo != activo:
            f.activo = activo
            actualizar.append(f)
    if actualizar:
        FacturaXLS.objects.bulk_update(actualizar, ["activo"])


def procesar_xml(ruta_xml: str, empresa: Empresa) -> None:
    """Procesa un XML UBL y crea/actualiza el FacturaXML correspondiente."""
    tree = ET.parse(ruta_xml)
    root = tree.getroot()
    cufe = _find_text(root, "cbc:UUID", required=True)
    fecha_text = _find_text(root, "cbc:IssueDate", required=True)
    fecha = parse_date(fecha_text)
    if fecha is None:
        raise ValueError("La fecha del documento no tiene un formato válido")
    proveedor_nombre = _find_text(
        root,
        "cac:AccountingSupplierParty/cac:Party/cac:PartyName/cbc:Name",
        required=True,
    )
    nit_proveedor = _find_text(
        root,
        "cac:AccountingSupplierParty/cac:Party/cac:PartyTaxScheme/cbc:CompanyID",
        required=True,
    )
    descripcion = _find_text(
        root,
        "cac:InvoiceLine/cac:Item/cbc:Description",
        default="",
    )
    subtotal = _parse_decimal(
        _find_text(root, "cac:LegalMonetaryTotal/cbc:LineExtensionAmount")
    )
    iva = _parse_decimal(_find_text(root, "cac:TaxTotal/cbc:TaxAmount"))
    total = _parse_decimal(
        _find_text(root, "cac:LegalMonetaryTotal/cbc:PayableAmount")
    )
    proveedor, _ = Proveedor.objects.get_or_create(
        empresa=empresa,
        nit=nit_proveedor,
        defaults={"nombre": proveedor_nombre},
    )
    FacturaXML.objects.get_or_create(
        empresa=empresa,
        cufe=cufe,
        defaults={
            "fecha": fecha,
            "descripcion": descripcion,
            "subtotal": subtotal,
            "iva": iva,
            "total": total,
            "proveedor": proveedor,
        },
    )


def _obtener_empresa_actual(request) -> Empresa | None:
    empresa_id = request.session.get("empresa_actual_id")
    if not empresa_id:
        return None
    try:
        return Empresa.objects.get(id=empresa_id, activo=True)
    except Empresa.DoesNotExist:
        return None


@login_required
def seleccionar_empresa(request):
    permisos = (
        PermisoEmpresa.objects.filter(usuario=request.user, empresa__activo=True)
        .select_related("empresa")
        .order_by("empresa__nombre")
    )
    if not permisos.exists():
        logout(request)
        messages.error(
            request,
            "No tienes empresas asignadas. Contacta con un administrador para obtener acceso.",
        )
        return redirect("login")

    if request.method == "POST":
        empresa_id = request.POST.get("empresa_id")
        permiso = permisos.filter(empresa_id=empresa_id).first()
        if permiso is None:
            messages.error(request, "No tienes acceso a la empresa seleccionada.")
        else:
            request.session["empresa_actual_id"] = permiso.empresa_id
            messages.success(
                request, f"Empresa {permiso.empresa.nombre} seleccionada correctamente."
            )
            return redirect("dashboard")

    empresa_actual = _obtener_empresa_actual(request)
    return render(
        request,
        "procesador/seleccionar_empresa.html",
        {
            "permisos": permisos,
            "empresa_actual": empresa_actual,
        },
    )


@login_required
def dashboard(request):
    """Vista principal del tablero de facturación."""
    ensure_fecha_documento_column()
    empresa = _obtener_empresa_actual(request)
    if empresa is None:
        messages.info(request, "Selecciona una empresa para continuar.")
        return redirect("seleccionar_empresa")
    if request.method == "POST":
        # Subir Excel
        if "upload_excel" in request.POST:
            form_excel = UploadExcelForm(request.POST, request.FILES)
            form_zip = UploadZipForm()
            if form_excel.is_valid():
                df = pd.read_excel(request.FILES["archivo"])
                for _, row in df.iterrows():
                    if row["Tipo de documento"] in [
                        "Factura electrónica",
                        "Documento soporte con no obligados",
                        "Nota de crédito electrónica",
                    ]:
                        fecha_excel = _extract_fecha_xls(row)
                        factura, _ = FacturaXLS.objects.get_or_create(
                            empresa=empresa,
                            cufe=row["CUFE/CUDE"],
                            defaults={
                                "tipo_documento": row["Tipo de documento"],
                                "folio": row.get("Folio"),
                                "prefijo": row.get("Prefijo"),
                                "nit_emisor": row.get("NIT Emisor"),
                                "nombre_emisor": row.get("Nombre Emisor"),
                                "fecha_documento": fecha_excel,
                                "iva": row.get("IVA", 0) or 0,
                                "inc": row.get("INC", 0) or 0,
                                "total": row.get("Total", 0) or 0,
                            },
                        )
                        if fecha_excel is not None:
                            factura.fecha_documento = fecha_excel
                        factura.activo = FacturaXML.objects.filter(
                            empresa=empresa, cufe=factura.cufe
                        ).exists()
                        factura.save()
                sincronizar_estado_facturas_xls(empresa)
                return redirect("dashboard")

        # Subir ZIP con XML
        elif "upload_zip" in request.POST:
            form_zip = UploadZipForm(request.POST, request.FILES)
            form_excel = UploadExcelForm()
            if form_zip.is_valid():
                archivo_zip = request.FILES["archivo"]
                with tempfile.TemporaryDirectory() as tmp:
                    ruta_zip = os.path.join(tmp, archivo_zip.name)
                    with open(ruta_zip, "wb") as f:
                        for chunk in archivo_zip.chunks():
                            f.write(chunk)
                    with zipfile.ZipFile(ruta_zip, "r") as z:
                        z.extractall(tmp)
                    for root_dir, _, files in os.walk(tmp):
                        for file in files:
                            if file.endswith(".xml"):
                                try:
                                    procesar_xml(os.path.join(root_dir, file), empresa)
                                except ValueError:
                                    continue
                sincronizar_estado_facturas_xls(empresa)
                return redirect("dashboard")
    else:
        form_excel = UploadExcelForm()
        form_zip = UploadZipForm()

    facturas_xml = (
        FacturaXML.objects.filter(empresa=empresa).select_related("proveedor")
    )
    facturas_xml_map = {fx.cufe: fx for fx in facturas_xml}
    facturas_xls = FacturaXLS.objects.filter(empresa=empresa)
    proveedores_empresa = {
        p.nit: p for p in Proveedor.objects.filter(empresa=empresa)
    }

    liquidacion_filas = []
    for factura in facturas_xls:
        subtotal = (
            _parse_decimal(factura.total)
            - _parse_decimal(factura.iva)
            - _parse_decimal(factura.inc)
        )
        iva = _parse_decimal(factura.iva)
        inc = _parse_decimal(factura.inc)
        factura_xml = facturas_xml_map.get(factura.cufe)
        proveedor = factura_xml.proveedor if factura_xml else None
        if proveedor is None and factura.nit_emisor:
            proveedor = proveedores_empresa.get(factura.nit_emisor)
        nit = factura.nit_emisor or (proveedor.nit if proveedor else "")
        proveedor_nombre = factura.nombre_emisor or (
            proveedor.nombre if proveedor else ""
        )
        fecha_excel = factura.fecha_documento
        fecha_excel_str = fecha_excel.isoformat() if fecha_excel else ""
        descripcion = factura_xml.descripcion if factura_xml else ""
        descripcion_display = (
            descripcion if factura_xml else "Sin coincidencia XML"
        )
        if factura.prefijo and factura.folio:
            prefijo_folio = f"{factura.prefijo}-{factura.folio}"
        else:
            prefijo_folio = factura.prefijo or factura.folio or ""

        total_neto_base = subtotal + iva + inc

        liquidacion_filas.append(
            {
                "factura_id": factura.id,
                "tipo_documento": factura.tipo_documento,
                "cufe": factura.cufe,
                "nit": nit,
                "proveedor_nombre": proveedor_nombre,
                "proveedor_id": proveedor.id if proveedor else None,
                "fecha": fecha_excel_str,
                "descripcion": descripcion,
                "descripcion_display": descripcion_display,
                "prefijo_folio": prefijo_folio,
                "subtotal": _decimal_to_str(subtotal),
                "subtotal_raw": str(subtotal),
                "iva": _decimal_to_str(iva),
                "iva_raw": str(iva),
                "inc": _decimal_to_str(inc),
                "inc_raw": str(inc),
                "retefuente": "0.00",
                "reteica": "0.00",
                "reteiva": "0.00",
                "total_neto": _decimal_to_str(total_neto_base),
                "total_neto_raw": str(total_neto_base),
                "coincide_xml": factura_xml is not None,
            }
        )

    return render(
        request,
        "procesador/dashboard.html",
        {
            "empresa": empresa,
            "form_excel": form_excel,
            "form_zip": form_zip,
            "facturas_xml": facturas_xml,
            "facturas_xls": facturas_xls,
            "liquidacion_filas": liquidacion_filas,
            "liquidacion_casilla_help": CASILLA_HELP_TEXT,
        },
    )


def _validar_filas_liquidacion(
    filas: list[dict],
    empresa: Empresa,
):
    if not isinstance(filas, list):
        return (
            [
                {
                    "fila": None,
                    "factura_id": None,
                    "campo": None,
                    "mensaje": "Formato inválido.",
                }
            ],
            [],
        )

    proveedor_ids = {
        fila.get("proveedor_id")
        for fila in filas
        if fila.get("proveedor_id")
    }

    _proveedores, catalogos_por_clave, catalogos_por_id = agrupar_catalogos_por_proveedor(
        proveedor_ids,
        empresa_id=empresa.id,
    )

    errores: list[dict] = []
    filas_resultado: list[dict] = []

    for indice, fila in enumerate(filas):
        importes = fila.get("importes") or {}
        cuentas = fila.get("cuentas") or {}
        porcentajes = fila.get("porcentajes") or {}
        proveedor_id = fila.get("proveedor_id")

        subtotal = _parse_decimal(importes.get("subtotal"))
        iva = _parse_decimal(importes.get("iva"))
        inc = _parse_decimal(importes.get("inc"))

        retefuente_val = Decimal("0")
        reteica_val = Decimal("0")
        reteiva_val = Decimal("0")

        casillas_resultado: dict[str, dict] = {}

        for casilla in CASILLAS:
            campo = CASILLA_FIELD_MAP[casilla]
            monto = _parse_decimal(importes.get(campo))
            monto_original = monto
            cuenta_id = cuentas.get(campo)
            porcentaje_input = (
                _parse_decimal(porcentajes.get(campo))
                if casilla in RETENCIONES
                else None
            )

            opciones = catalogos_por_clave.get((proveedor_id, casilla), [])
            catalogo = None
            catalogo_valido = True

            if monto != Decimal("0"):
                if not opciones:
                    errores.append(
                        {
                            "fila": indice,
                            "factura_id": fila.get("factura_id"),
                            "campo": campo,
                            "mensaje": CASILLA_RULES[casilla][
                                "mensaje_sin_opciones"
                            ],
                        }
                    )
                elif cuenta_id in (None, ""):
                    errores.append(
                        {
                            "fila": indice,
                            "factura_id": fila.get("factura_id"),
                            "campo": campo,
                            "mensaje": CAMPO_OBLIGATORIO_MSG,
                        }
                    )

            if cuenta_id not in (None, ""):
                try:
                    catalogo = catalogos_por_id.get(int(cuenta_id))
                except (TypeError, ValueError):
                    catalogo = None
                if catalogo is None:
                    errores.append(
                        {
                            "fila": indice,
                            "factura_id": fila.get("factura_id"),
                            "campo": campo,
                            "mensaje": CUENTA_PROVEEDOR_MSG,
                        }
                    )
                    catalogo_valido = False
                elif proveedor_id is None or catalogo.proveedor_id != proveedor_id:
                    errores.append(
                        {
                            "fila": indice,
                            "factura_id": fila.get("factura_id"),
                            "campo": campo,
                            "mensaje": CUENTA_PROVEEDOR_MSG,
                        }
                    )
                    catalogo_valido = False
                elif catalogo.casilla != casilla:
                    errores.append(
                        {
                            "fila": indice,
                            "factura_id": fila.get("factura_id"),
                            "campo": campo,
                            "mensaje": CASILLA_ERROR_MSG,
                        }
                    )
                    catalogo_valido = False
                else:
                    mensaje_prefijo = validar_prefijo_para_casilla(
                        casilla, catalogo.cuenta.codigo
                    )
                    if mensaje_prefijo:
                        errores.append(
                            {
                                "fila": indice,
                                "factura_id": fila.get("factura_id"),
                                "campo": campo,
                                "mensaje": mensaje_prefijo,
                            }
                        )
                        catalogo_valido = False
                if (
                    catalogo_valido
                    and catalogo is not None
                    and catalogo.naturaleza
                    != CASILLA_RULES[casilla]["naturaleza"]
                ):
                    errores.append(
                        {
                            "fila": indice,
                            "factura_id": fila.get("factura_id"),
                            "campo": campo,
                            "mensaje": NATURALEZA_ERROR_MSG,
                        }
                    )
                    catalogo_valido = False

            casilla_info = {
                "monto": monto,
                "catalogo": catalogo if catalogo_valido else None,
                "porcentaje": None,
                "valor": None,
                "naturaleza": (
                    catalogo.naturaleza
                    if catalogo_valido and catalogo is not None
                    else CASILLA_RULES[casilla]["naturaleza"]
                ),
            }

            if (
                casilla in RETENCIONES
                and catalogo_valido
                and catalogo is not None
            ):
                if catalogo.porcentaje is None:
                    errores.append(
                        {
                            "fila": indice,
                            "factura_id": fila.get("factura_id"),
                            "campo": campo,
                            "mensaje": CASILLA_RULES[casilla][
                                "mensaje_sin_opciones"
                            ],
                        }
                    )
                else:
                    porcentaje_calc, valor_calc = calcular_retencion(
                        subtotal, catalogo
                    )
                    casilla_info["porcentaje"] = porcentaje_calc
                    casilla_info["valor"] = valor_calc
                    casilla_info["monto"] = valor_calc
                    if casilla == "RETEFUENTE":
                        retefuente_val = valor_calc
                    elif casilla == "RETEICA":
                        reteica_val = valor_calc
                    elif casilla == "RETEIVA":
                        reteiva_val = valor_calc
            elif casilla in RETENCIONES:
                casilla_info["porcentaje"] = (
                    porcentaje_input if porcentaje_input is not None else Decimal("0")
                )
                casilla_info["valor"] = monto
                if casilla == "RETEFUENTE":
                    retefuente_val = monto
                elif casilla == "RETEICA":
                    reteica_val = monto
                elif casilla == "RETEIVA":
                    reteiva_val = monto
            else:
                casilla_info["valor"] = monto

            if casilla == "TOTAL_NETO":
                total_calculado = subtotal + iva + inc - retefuente_val - reteica_val - reteiva_val
                casilla_info["valor"] = total_calculado
                casilla_info["monto"] = total_calculado
                if total_calculado != Decimal("0") and cuenta_id in (None, ""):
                    errores.append(
                        {
                            "fila": indice,
                            "factura_id": fila.get("factura_id"),
                            "campo": campo,
                            "mensaje": CAMPO_OBLIGATORIO_MSG,
                        }
                    )

            casillas_resultado[casilla] = casilla_info

        filas_resultado.append(
            {
                "indice": indice,
                "factura_id": fila.get("factura_id"),
                "proveedor_id": proveedor_id,
                "original": fila,
                "casillas": casillas_resultado,
                "subtotal": subtotal,
                "iva": iva,
                "inc": inc,
                "retefuente": retefuente_val,
                "reteica": reteica_val,
                "reteiva": reteiva_val,
                "total_neto": subtotal + iva + inc - retefuente_val - reteica_val - reteiva_val,
            }
        )

    return errores, filas_resultado


def _serializar_fila_validada(fila: dict) -> dict:
    datos = {
        "indice": fila["indice"],
        "factura_id": fila["factura_id"],
        "proveedor_id": fila["proveedor_id"],
        "importes": {},
        "cuentas": {},
        "porcentajes": {},
    }

    for casilla, info in fila["casillas"].items():
        campo = CASILLA_FIELD_MAP[casilla]
        datos["importes"][campo] = _decimal_to_str(info["valor"] or info["monto"])
        datos["cuentas"][campo] = (
            info["catalogo"].id if info["catalogo"] is not None else None
        )
        if casilla in RETENCIONES:
            porcentaje = info.get("porcentaje") or Decimal("0")
            datos["porcentajes"][campo] = _decimal_to_str(porcentaje, places=4)

    datos["total_neto_calculado"] = _decimal_to_str(fila["total_neto"])
    return datos


@login_required
@require_GET
def liquidacion_catalogos(request, proveedor_id: int):
    empresa = _obtener_empresa_actual(request)
    if empresa is None:
        return JsonResponse(
            {"detail": "Selecciona una empresa para continuar."}, status=400
        )

    try:
        proveedor = Proveedor.objects.get(pk=proveedor_id, empresa=empresa)
    except Proveedor.DoesNotExist:
        return JsonResponse({"detail": "Proveedor no encontrado."}, status=404)

    catalogos = (
        CuentaContableProveedor.objects.filter(proveedor=proveedor, activo=True)
        .select_related("cuenta")
        .order_by("casilla", "cuenta__codigo")
    )

    respuesta = {clave: [] for clave in CATALOGO_RESPONSE_KEYS.values()}
    for item in catalogos:
        entry = {
            "id": item.id,
            "codigo": item.cuenta.codigo,
            "descripcion": item.cuenta.descripcion,
            "naturaleza": item.naturaleza,
        }
        if item.porcentaje is not None:
            entry["porcentaje"] = _decimal_to_str(item.porcentaje, places=4)
        if item.modo_calculo:
            entry["modo_calculo"] = item.modo_calculo
        if item.ayuda:
            entry["ayuda"] = item.ayuda
        respuesta[CATALOGO_RESPONSE_KEYS[item.casilla]].append(entry)

    return JsonResponse(
        {
            "proveedor": {
                "id": proveedor.id,
                "nombre": proveedor.nombre,
                "nit": proveedor.nit,
            },
            "catalogos": respuesta,
        }
    )


@login_required
@require_POST
def liquidacion_validar(request):
    empresa = _obtener_empresa_actual(request)
    if empresa is None:
        return JsonResponse(
            {"detail": "Selecciona una empresa para continuar."}, status=400
        )

    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"detail": "JSON inválido."}, status=400)

    filas = payload.get("filas", [])
    errores, filas_resultado = _validar_filas_liquidacion(filas, empresa)

    return JsonResponse(
        {
            "valido": not errores,
            "errores": errores,
            "filas": [_serializar_fila_validada(fila) for fila in filas_resultado],
        },
        status=200 if not errores else 400,
    )


@login_required
@require_GET
def liquidacion_exportar(request):
    ensure_fecha_documento_column()
    empresa = _obtener_empresa_actual(request)
    if empresa is None:
        messages.info(request, "Selecciona una empresa para continuar.")
        return redirect("seleccionar_empresa")

    formato = request.GET.get("formato")
    if formato != "csv":
        return JsonResponse({"detail": "Formato no soportado."}, status=400)

    payload = request.GET.get("payload", "{}")
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return JsonResponse({"detail": "JSON inválido."}, status=400)

    filas = data.get("filas", [])
    errores, filas_resultado = _validar_filas_liquidacion(filas, empresa)
    if errores:
        return JsonResponse({"errores": errores}, status=400)

    import csv
    import io

    buffer = io.StringIO()
    fieldnames = [
        "Tipo documento",
        "CUFE/CUDE",
        "NIT",
        "Proveedor",
        "Fecha",
        "Descripción",
        "Prefijo + Folio",
        "Sub total",
        "Sub total – Cuenta contable",
        "IVA",
        "IVA – Cuenta contable",
        "INC",
        "INC – Cuenta contable",
        "ReteFuente (%)",
        "ReteFuente (valor)",
        "ReteFuente – Cuenta contable",
        "ReteICA (%)",
        "ReteICA (valor)",
        "ReteICA – Cuenta contable",
        "ReteIva (%)",
        "ReteIva (valor)",
        "ReteIva – Cuenta contable",
        "Total neto",
        "Total neto – Cuenta contable",
    ]
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()

    for fila in filas_resultado:
        original = fila.get("original", {})
        casillas = fila.get("casillas", {})

        def obtener_cuenta(casilla: str) -> str:
            info = casillas.get(casilla, {})
            catalogo = info.get("catalogo")
            return catalogo.cuenta.codigo if catalogo else ""

        def obtener_monto(casilla: str) -> Decimal:
            info = casillas.get(casilla, {})
            valor = info.get("valor")
            if valor is None:
                valor = info.get("monto", Decimal("0"))
            naturaleza = info.get("naturaleza", CASILLA_RULES[casilla]["naturaleza"])
            signo = signo_por_naturaleza(naturaleza)
            return (valor or Decimal("0")) * signo

        def obtener_porcentaje(casilla: str) -> str:
            info = casillas.get(casilla, {})
            porcentaje = info.get("porcentaje")
            if porcentaje is None:
                porcentaje = Decimal("0")
            return _decimal_to_str(porcentaje, places=4)

        subtotal_val = casillas.get("SUBTOTAL", {}).get("valor", fila["subtotal"])
        iva_val = casillas.get("IVA", {}).get("valor", fila["iva"])
        inc_val = casillas.get("INC", {}).get("valor", fila["inc"])
        total_neto_val = fila["total_neto"]

        writer.writerow(
            {
                "Tipo documento": original.get("tipo_documento", ""),
                "CUFE/CUDE": original.get("cufe", ""),
                "NIT": original.get("nit", ""),
                "Proveedor": original.get("proveedor", ""),
                "Fecha": original.get("fecha", ""),
                "Descripción": original.get("descripcion", ""),
                "Prefijo + Folio": original.get("prefijo_folio", ""),
                "Sub total": _decimal_to_str(subtotal_val),
                "Sub total – Cuenta contable": obtener_cuenta("SUBTOTAL"),
                "IVA": _decimal_to_str(iva_val),
                "IVA – Cuenta contable": obtener_cuenta("IVA"),
                "INC": _decimal_to_str(inc_val),
                "INC – Cuenta contable": obtener_cuenta("INC"),
                "ReteFuente (%)": obtener_porcentaje("RETEFUENTE"),
                "ReteFuente (valor)": _decimal_to_str(
                    obtener_monto("RETEFUENTE")
                ),
                "ReteFuente – Cuenta contable": obtener_cuenta("RETEFUENTE"),
                "ReteICA (%)": obtener_porcentaje("RETEICA"),
                "ReteICA (valor)": _decimal_to_str(
                    obtener_monto("RETEICA")
                ),
                "ReteICA – Cuenta contable": obtener_cuenta("RETEICA"),
                "ReteIva (%)": obtener_porcentaje("RETEIVA"),
                "ReteIva (valor)": _decimal_to_str(
                    obtener_monto("RETEIVA")
                ),
                "ReteIva – Cuenta contable": obtener_cuenta("RETEIVA"),
                "Total neto": _decimal_to_str(total_neto_val),
                "Total neto – Cuenta contable": obtener_cuenta("TOTAL_NETO"),
            }
        )

    response = HttpResponse(
        buffer.getvalue(), content_type="text/csv; charset=utf-8"
    )
    response[
        "Content-Disposition"
    ] = 'attachment; filename="liquidacion_facturas.csv"'
    return response
