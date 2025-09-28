import os, zipfile, tempfile
import xml.etree.ElementTree as ET
import pandas as pd
from django.shortcuts import render, redirect
from .forms import UploadExcelForm, UploadZipForm
from .models import FacturaXML, Proveedor, FacturaXLS

# Namespaces DIAN
ns = {
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
}

def procesar_xml(ruta_xml):
    """Procesar un archivo XML y guardarlo en la base de datos"""
    tree = ET.parse(ruta_xml)
    root = tree.getroot()

    cufe = root.find("cbc:UUID", ns).text
    fecha = root.find("cbc:IssueDate", ns).text
    proveedor_nombre = root.find("cac:AccountingSupplierParty/cac:Party/cac:PartyName/cbc:Name", ns).text
    nit_proveedor = root.find("cac:AccountingSupplierParty/cac:Party/cac:PartyTaxScheme/cbc:CompanyID", ns).text
    descripcion = root.find("cac:InvoiceLine/cac:Item/cbc:Description", ns).text
    subtotal = root.find("cac:LegalMonetaryTotal/cbc:LineExtensionAmount", ns).text
    iva = root.find("cac:TaxTotal/cbc:TaxAmount", ns).text
    total = root.find("cac:LegalMonetaryTotal/cbc:PayableAmount", ns).text

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
        }
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
                        factura.activo = FacturaXML.objects.filter(cufe=factura.cufe).exists()
                        factura.save()

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
                                procesar_xml(os.path.join(root_dir, file))

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
