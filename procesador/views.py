from __future__ import annotations
import os, tempfile, zipfile
from decimal import Decimal, InvalidOperation
import xml.etree.ElementTree as ET
import pandas as pd
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils.dateparse import parse_date

from .forms import UploadExcelForm, UploadZipForm
from .models import FacturaXML, FacturaXLS, Proveedor, Retencion, TarifaICA

ns = {
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
}

def _find_text(element, path, *, required=False, default=None):
    node = element.find(path, ns)
    if node is not None and node.text is not None:
        return node.text.strip()
    if required:
        raise ValueError(f"El nodo requerido '{path}' no se encontró en el XML")
    return default

def _parse_decimal(value, default=Decimal("0")):
    if value is None:
        return default
    cleaned = str(value).strip().replace("$", "")
    if not cleaned:
        return default
    if cleaned.count(",") == 1 and cleaned.count(".") == 0:
        cleaned = cleaned.replace(",", ".")
    else:
        cleaned = cleaned.replace(",", "")
    try:
        return Decimal(cleaned)
    except (InvalidOperation, TypeError):
        return default

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
    tree = ET.parse(ruta_xml)
    root = tree.getroot()
    cufe = _find_text(root, "cbc:UUID", required=True)
    fecha_text = _find_text(root, "cbc:IssueDate", required=True)
    fecha = parse_date(fecha_text)
    if fecha is None:
        raise ValueError("La fecha del documento no tiene un formato válido")
    proveedor_nombre = _find_text(root, "cac:AccountingSupplierParty/cac:Party/cac:PartyName/cbc:Name", required=True)
    nit_proveedor = _find_text(root, "cac:AccountingSupplierParty/cac:Party/cac:PartyTaxScheme/cbc:CompanyID", required=True)
    descripcion = _find_text(root, "cac:InvoiceLine/cac:Item/cbc:Description", default="")
    subtotal = _parse_decimal(_find_text(root, "cac:LegalMonetaryTotal/cbc:LineExtensionAmount"))
    iva = _parse_decimal(_find_text(root, "cac:TaxTotal/cbc:TaxAmount"))
    total = _parse_decimal(_find_text(root, "cac:LegalMonetaryTotal/cbc:PayableAmount"))
    proveedor, _ = Proveedor.objects.get_or_create(nit=nit_proveedor, defaults={"nombre": proveedor_nombre})
    FacturaXML.objects.get_or_create(
        cufe=cufe,
        defaults={"fecha": fecha, "descripcion": descripcion, "subtotal": subtotal, "iva": iva, "total": total, "proveedor": proveedor},
    )

def dashboard(request):
    if request.method == "POST":
        # Subir Excel
        if "upload_excel" in request.POST:
            form_excel = UploadExcelForm(request.POST, request.FILES)
            form_zip = UploadZipForm()
            if form_excel.is_valid():
                df = pd.read_excel(request.FILES["archivo"])
                for _, row in df.iterrows():
                    if row["Tipo de documento"] in ["Factura electrónica", "Documento soporte con no obligados", "Nota de crédito electrónica"]:
                        factura, _ = FacturaXLS.objects.get_or_create(
                            cufe=row["CUFE/CUDE"],
                            defaults={
                                "tipo_documento": row["Tipo de documento"],
                                "folio": row.get("Folio"),
                                "prefijo": row.get("Prefijo"),
                                "nit_emisor": row.get("NIT Emisor"),
                                "nombre_emisor": row.get("Nombre Emisor"),
                                "iva": row.get("IVA", 0) or 0,
                                "inc": row.get("INC", 0) or 0,
                                "total": row.get("Total", 0) or 0,
                            },
                        )
                        factura.activo = FacturaXML.objects.filter(cufe=factura.cufe).exists()
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

    facturas_xml = FacturaXML.objects.all()
    facturas_xls = FacturaXLS.objects.all()

    # --- NUEVO: datos para la pestaña Liquidación ---
    tarifas_ica = list(TarifaICA.objects.all().values_list("valor", flat=True))
    if not tarifas_ica:
        tarifas_ica = [Decimal("4.14"), Decimal("8.66"), Decimal("9.66"), Decimal("13.8")]

    liquidaciones = []
    for f in facturas_xls:
        subtotal = _parse_decimal(f.total) - _parse_decimal(f.iva) - _parse_decimal(f.inc)
        proveedor = Proveedor.objects.filter(nit=f.nit_emisor).first()
        retenciones = Retencion.objects.filter(proveedor=proveedor).order_by("porcentaje") if proveedor else Retencion.objects.none()
        opciones_rf = [r.porcentaje for r in retenciones] or [Decimal("0"), Decimal("2.5"), Decimal("4"), Decimal("3.5"), Decimal("11"), Decimal("1")]
        liquidaciones.append({
            "factura": f,
            "subtotal": subtotal,
            "opciones_rf": opciones_rf,
            "opciones_ica": tarifas_ica,
        })

    return render(request, "procesador/dashboard.html", {
        "form_excel": form_excel,
        "form_zip": form_zip,
        "facturas_xml": facturas_xml,
        "facturas_xls": facturas_xls,
        "liquidaciones": liquidaciones,  # <-- para la nueva pestaña
    })

def descargar_liquidacion_csv(request):
    """
    Exporta un CSV simple. Por ahora acepta filtros globales opcionales:
      ?rf=2.5&ica=8.66
    Si no se pasan, se asume 0 para ambos (luego lo afinamos por-factura).
    """
    rf = _parse_decimal(request.GET.get("rf"), Decimal("0"))
    ica = _parse_decimal(request.GET.get("ica"), Decimal("0"))

    rows = []
    for f in FacturaXLS.objects.all():
        subtotal = _parse_decimal(f.total) - _parse_decimal(f.iva) - _parse_decimal(f.inc)
        retefuente = (subtotal * rf) / Decimal("100")
        reteica = (subtotal * ica) / Decimal("100")  # si luego manejas por-mil, lo cambiamos
        total_neto = subtotal + _parse_decimal(f.iva) + _parse_decimal(f.inc) - retefuente - reteica
        rows.append({
            "CUFE/CUDE": f.cufe,
            "NIT Emisor": f.nit_emisor,
            "Nombre Emisor": f.nombre_emisor,
            "Subtotal": f"{subtotal:.2f}",
            "IVA": f"{_parse_decimal(f.iva):.2f}",
            "INC": f"{_parse_decimal(f.inc):.2f}",
            "ReteFuente(%)": f"{rf}",
            "ReteICA(%)": f"{ica}",
            "Total Neto": f"{total_neto:.2f}",
        })

    # construir CSV
    import csv, io
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()) if rows else ["Mensaje"])
    writer.writeheader()
    if rows:
        writer.writerows(rows)
    else:
        writer.writerow({"Mensaje": "Sin datos"})
    resp = HttpResponse(buffer.getvalue(), content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = 'attachment; filename="liquidacion_facturas.csv"'
    return resp
# --- FIN NUEVO ---