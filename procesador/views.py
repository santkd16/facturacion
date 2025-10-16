from __future__ import annotations
import json
import os
import tempfile
import zipfile
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import xml.etree.ElementTree as ET
import pandas as pd
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils.dateparse import parse_date

from .forms import UploadExcelForm, UploadZipForm
from .models import FacturaXML, FacturaXLS, Proveedor, Retencion, TarifaICA

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


def sincronizar_estado_facturas_xls():
    xml_cufes = set(FacturaXML.objects.values_list("cufe", flat=True))
    actualizar = []
    for f in FacturaXLS.objects.all().only("id", "cufe", "activo"):
        activo = f.cufe in xml_cufes
        if f.activo != activo:
            f.activo = activo
            actualizar.append(f)
    if actualizar:
        FacturaXLS.objects.bulk_update(actualizar, ["activo"])


def procesar_xml(ruta_xml: str) -> None:
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
        nit=nit_proveedor,
        defaults={"nombre": proveedor_nombre},
    )
    FacturaXML.objects.get_or_create(
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


def dashboard(request):
    """Vista principal del tablero de facturación."""
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
                            cufe=factura.cufe
                        ).exists()
                        factura.save()
                sincronizar_estado_facturas_xls()
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
                                    procesar_xml(os.path.join(root_dir, file))
                                except ValueError:
                                    continue
                sincronizar_estado_facturas_xls()
                return redirect("dashboard")
    else:
        form_excel = UploadExcelForm()
        form_zip = UploadZipForm()

    facturas_xml = FacturaXML.objects.select_related("proveedor")
    facturas_xml_map = {fx.cufe: fx for fx in facturas_xml}
    facturas_xls = FacturaXLS.objects.all()

    # --- NUEVO: datos para la pestaña Liquidación ---
    # Obtener tarifas ICA; si no existen, usar valores por defecto.
    tarifas_ica = sorted(
        TarifaICA.objects.all().values_list("valor", flat=True)
    )
    if not tarifas_ica:
        tarifas_ica = [
            Decimal("0.414"),
            Decimal("0.866"),
            Decimal("0.966"),
            Decimal("1.38"),
        ]
    if Decimal("0") not in tarifas_ica:
        tarifas_ica.insert(0, Decimal("0"))

    liquidaciones = []
    for f in facturas_xls:
        subtotal = (
            _parse_decimal(f.total)
            - _parse_decimal(f.iva)
            - _parse_decimal(f.inc)
        )
        
        factura_xml = facturas_xml_map.get(f.cufe)
        proveedor = factura_xml.proveedor if factura_xml else None
        nit = f.nit_emisor or (proveedor.nit if proveedor else "")
        proveedor_nombre = (
            f.nombre_emisor or (proveedor.nombre if proveedor else "")
        )
        fecha_excel = f.fecha_documento
        fecha_xml = factura_xml.fecha if factura_xml else None
        fecha = fecha_excel if fecha_excel is not None else None
        fecha = factura_xml.fecha if factura_xml else None
        descripcion = factura_xml.descripcion if factura_xml else ""
        coincide_xml = factura_xml is not None
        descripcion_display = descripcion if coincide_xml else "Sin coincidencia XML"
        if f.prefijo and f.folio:
            prefijo_folio = f"{f.prefijo}-{f.folio}"
        else:
            prefijo_folio = f.prefijo or f.folio or ""

        # Opciones de retefuente por proveedor; si no hay, usar valores base.
        retenciones = (
            Retencion.objects.filter(proveedor=proveedor).order_by("porcentaje")
            if proveedor
            else Retencion.objects.none()
        )
        opciones_rf = [r.porcentaje for r in retenciones] or [
            Decimal("0"),
            Decimal("2.5"),
            Decimal("4"),
            Decimal("3.5"),
            Decimal("11"),
            Decimal("1"),
        ]
        rf_por_defecto = opciones_rf[0] if opciones_rf else Decimal("0")
        ica_por_defecto = tarifas_ica[0] if tarifas_ica else Decimal("0")

        liquidaciones.append(
            {
                "factura": f,
                "subtotal": subtotal,
                "opciones_rf": opciones_rf,
                "opciones_ica": tarifas_ica,
                "retefuente_default": rf_por_defecto,
                "reteica_default": ica_por_defecto,
                "nit": nit,
                "proveedor_nombre": proveedor_nombre,
                "fecha_excel": fecha_excel,
                "fecha_xml": fecha_xml,
                "fecha": fecha,
                "prefijo_folio": prefijo_folio,
                "descripcion": descripcion,
                "descripcion_display": descripcion_display,
                "coincide_xml": coincide_xml,
            }
        )

    return render(
        request,
        "procesador/dashboard.html",
        {
            "form_excel": form_excel,
            "form_zip": form_zip,
            "facturas_xml": facturas_xml,
            "facturas_xls": facturas_xls,
            "liquidaciones": liquidaciones,
        },
    )


def descargar_liquidacion_csv(request):
    """Exporta un CSV con la liquidación global.

    Si la petición es POST se espera un payload JSON con la información
    mostrada en la tabla del dashboard, incluyendo las retenciones
    seleccionadas por el usuario. En caso contrario, se genera un CSV con
    los valores por defecto sin aplicar retenciones.
    """

    import csv
    import io

    rows: list[dict[str, str]] = []

    if request.method == "POST":
        payload = request.POST.get("rows_json", "[]")
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            data = []

        for entry in data:
            subtotal = _parse_decimal(entry.get("subtotal"))
            iva = _parse_decimal(entry.get("iva"))
            inc = _parse_decimal(entry.get("inc"))
            rf_pct = _parse_decimal(entry.get("retefuente_pct"))
            ica_pct = _parse_decimal(entry.get("reteica_pct"))
            retefuente = (subtotal * rf_pct) / Decimal("100")
            reteica = (subtotal * ica_pct) / Decimal("100")
            total_neto = subtotal + iva + inc - retefuente - reteica
            rows.append(
                {
                    "Tipo de documento": entry.get("tipo_documento", ""),
                    "CUFE/CUDE": entry.get("cufe", ""),
                    "NIT": entry.get("nit", ""),
                    "Proveedor": entry.get("proveedor", ""),
                    "Fecha": entry.get("fecha", ""),
                    "Descripción": entry.get("descripcion", ""),
                    "Prefijo+Folio": entry.get("prefijo_folio", ""),
                    "Sub total": f"{subtotal:.2f}",
                    "IVA": f"{iva:.2f}",
                    "INC": f"{inc:.2f}",
                    "ReteFuente": f"{retefuente:.2f}",
                    "ReteICA": f"{reteica:.2f}",
                    "Total neto": f"{total_neto:.2f}",
                }
            )
    else:
        facturas_xml = {
            fx.cufe: fx
            for fx in FacturaXML.objects.select_related("proveedor")
        }

        for factura in FacturaXLS.objects.all():
            subtotal = (
                _parse_decimal(factura.total)
                - _parse_decimal(factura.iva)
                - _parse_decimal(factura.inc)
            )
            factura_xml = facturas_xml.get(factura.cufe)
            nit = factura.nit_emisor or (
                factura_xml.proveedor.nit if factura_xml else ""
            )
            proveedor = factura.nombre_emisor or (
                factura_xml.proveedor.nombre if factura_xml else ""
            )
            fecha = (
                factura.fecha_documento.isoformat()
                if factura.fecha_documento
                else ""
            )
            fecha = factura_xml.fecha.isoformat() if factura_xml else ""
            descripcion = factura_xml.descripcion if factura_xml else ""
            if factura.prefijo and factura.folio:
                prefijo_folio = f"{factura.prefijo}-{factura.folio}"
            else:
                prefijo_folio = factura.prefijo or factura.folio or ""

            total_neto = subtotal + _parse_decimal(factura.iva) + _parse_decimal(
                factura.inc
            )
            rows.append(
                {
                    "Tipo de documento": factura.tipo_documento,
                    "CUFE/CUDE": factura.cufe,
                    "NIT": nit,
                    "Proveedor": proveedor,
                    "Fecha": fecha,
                    "Descripción": descripcion,
                    "Prefijo+Folio": prefijo_folio,
                    "Sub total": f"{subtotal:.2f}",
                    "IVA": f"{_parse_decimal(factura.iva):.2f}",
                    "INC": f"{_parse_decimal(factura.inc):.2f}",
                    "ReteFuente": "0.00",
                    "ReteICA": "0.00",
                    "Total neto": f"{total_neto:.2f}",
                }
            )

    buffer = io.StringIO()
    fieldnames = [
        "Tipo de documento",
        "CUFE/CUDE",
        "NIT",
        "Proveedor",
        "Fecha",
        "Descripción",
        "Prefijo+Folio",
        "Sub total",
        "IVA",
        "INC",
        "ReteFuente",
        "ReteICA",
        "Total neto",
    ]
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    if rows:
        writer.writerows(rows)
    else:
        writer.writerow({"Tipo de documento": "Sin datos"})

    response = HttpResponse(
        buffer.getvalue(), content_type="text/csv; charset=utf-8"
    )
    response[
        "Content-Disposition"
    ] = 'attachment; filename="liquidacion_facturas.csv"'
    return response
