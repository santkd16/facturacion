import os
import tempfile
import zipfile
from decimal import Decimal, InvalidOperation
import xml.etree.ElementTree as ET

import pandas as pd
from django.shortcuts import redirect, render
from django.utils.dateparse import parse_date

from .forms import UploadExcelForm, UploadZipForm
from .models import FacturaXML, FacturaXLS, Proveedor

# Namespaces DIAN
ns = {
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
}

def _find_text(element, path, *, required=False, default=None):
    """Obtener el texto de un nodo XML manejando campos faltantes."""
    node = element.find(path, ns)
    if node is not None and node.text is not None:
        return node.text.strip()
    if required:
        raise ValueError(f"El nodo requerido '{path}' no se encontró en el XML")
    return default


def _parse_decimal(value, default=Decimal("0")):
    """Convertir valores numéricos representados como texto a Decimal."""
    if value is None:
        return default

    cleaned = value.strip().replace("$", "")
    if not cleaned:
        return default

    # Manejar diferentes convenciones de miles y decimales
    if cleaned.count(",") == 1 and cleaned.count(".") == 0:
        cleaned = cleaned.replace(",", ".")
    else:
        cleaned = cleaned.replace(",", "")

    try:
        return Decimal(cleaned)
    except (InvalidOperation, TypeError):
        return default


def sincronizar_estado_facturas_xls():
    """Actualizar el estado activo de las facturas XLS según los XML disponibles."""

    xml_cufes = set(
        FacturaXML.objects.values_list("cufe", flat=True)
    )  # se evalúa inmediatamente

    facturas_a_actualizar = []
    for factura in FacturaXLS.objects.all().only("id", "cufe", "activo"):
        debe_estar_activo = factura.cufe in xml_cufes
        if factura.activo != debe_estar_activo:
            factura.activo = debe_estar_activo
            facturas_a_actualizar.append(factura)

    if facturas_a_actualizar:
        FacturaXLS.objects.bulk_update(facturas_a_actualizar, ["activo"])


def procesar_xml(ruta_xml):
    """Procesar un archivo XML y guardarlo en la base de datos."""
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
        root, "cac:InvoiceLine/cac:Item/cbc:Description", default=""
    )
    subtotal = _parse_decimal(
        _find_text(root, "cac:LegalMonetaryTotal/cbc:LineExtensionAmount")
    )
    iva = _parse_decimal(_find_text(root, "cac:TaxTotal/cbc:TaxAmount"))
    total = _parse_decimal(
        _find_text(root, "cac:LegalMonetaryTotal/cbc:PayableAmount")
    )

    proveedor, _ = Proveedor.objects.get_or_create(
        nit=nit_proveedor, defaults={"nombre": proveedor_nombre}
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
    """Vista principal del dashboard"""
    if request.method == "POST":
        # 📌 Subida de Excel
        if "upload_excel" in request.POST:
            form_excel = UploadExcelForm(request.POST, request.FILES)
            form_zip = UploadZipForm()
            if form_excel.is_valid():
                archivo_excel = request.FILES["archivo"]
                df = pd.read_excel(archivo_excel)

                for _, row in df.iterrows():
                    # Filtrar solo documentos que nos interesan
                    if row["Tipo de documento"] in [
                        "Factura electrónica",
                        "Documento soporte con no obligados",
                        "Nota de crédito electrónica",
                    ]:
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

                        # Marcar activo si también existe en XML
                        factura.activo = FacturaXML.objects.filter(
                            cufe=factura.cufe
                        ).exists()
                        factura.save()

                sincronizar_estado_facturas_xls()

                return redirect("dashboard")

        # 📌 Subida de ZIP con XML
        elif "upload_zip" in request.POST:
            form_zip = UploadZipForm(request.POST, request.FILES)
            form_excel = UploadExcelForm()
            if form_zip.is_valid():
                archivo_zip = request.FILES["archivo"]

                with tempfile.TemporaryDirectory() as tmpdirname:
                    ruta_zip = os.path.join(tmpdirname, archivo_zip.name)
                    with open(ruta_zip, "wb") as f:
                        for chunk in archivo_zip.chunks():
                            f.write(chunk)

                    with zipfile.ZipFile(ruta_zip, "r") as zip_ref:
                        zip_ref.extractall(tmpdirname)

                    for root_dir, dirs, files in os.walk(tmpdirname):
                        for file in files:
                            if file.endswith(".xml"):
                                try:
                                    procesar_xml(os.path.join(root_dir, file))
                                except ValueError:
                                    # Ignorar archivos con estructura inválida
                                    continue

                sincronizar_estado_facturas_xls()

                return redirect("dashboard")
    else:
        form_excel = UploadExcelForm()
        form_zip = UploadZipForm()

    facturas_xml = FacturaXML.objects.all()
    facturas_xls = FacturaXLS.objects.all()

    return render(request, "procesador/dashboard.html", {
        "form_excel": form_excel,
        "form_zip": form_zip,
        "facturas_xml": facturas_xml,
        "facturas_xls": facturas_xls,
    })
