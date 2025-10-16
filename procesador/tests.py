import csv
import os
import tempfile
import zipfile
from io import BytesIO
from datetime import date
from decimal import Decimal

import pandas as pd
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from .models import FacturaXML, FacturaXLS, Proveedor
from .views import _extract_fecha_xls, procesar_xml, sincronizar_estado_facturas_xls


def _write_xml(content: str) -> str:
    temp = tempfile.NamedTemporaryFile(
        delete=False, suffix=".xml", mode="w", encoding="utf-8"
    )
    try:
        temp.write(content)
        temp.flush()
    finally:
        temp.close()
    return temp.name


class ExtraerFechaXLSTests(TestCase):
    def test_extrae_desde_timestamp(self):
        fila = pd.Series({"Fecha": pd.Timestamp("2024-05-10")})
        self.assertEqual(_extract_fecha_xls(fila), date(2024, 5, 10))

    def test_extrae_desde_cadena(self):
        fila = pd.Series({"Fecha documento": "2024-06-01"})
        self.assertEqual(_extract_fecha_xls(fila), date(2024, 6, 1))

    def test_devuelve_none_si_no_hay_fecha(self):
        fila = pd.Series({"Tipo de documento": "Factura electrónica"})
        self.assertIsNone(_extract_fecha_xls(fila))


class ProcesarXMLTests(TestCase):
    def test_procesar_xml_crea_factura_y_proveedor(self):
        xml_content = """<?xml version='1.0' encoding='UTF-8'?>
        <Invoice xmlns='urn:oasis:names:specification:ubl:schema:xsd:Invoice-2'
                 xmlns:cac='urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2'
                 xmlns:cbc='urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2'>
            <cbc:UUID>123ABC</cbc:UUID>
            <cbc:IssueDate>2024-01-20</cbc:IssueDate>
            <cac:AccountingSupplierParty>
                <cac:Party>
                    <cac:PartyName>
                        <cbc:Name>Proveedor Demo</cbc:Name>
                    </cac:PartyName>
                    <cac:PartyTaxScheme>
                        <cbc:CompanyID>900123456</cbc:CompanyID>
                    </cac:PartyTaxScheme>
                </cac:Party>
            </cac:AccountingSupplierParty>
            <cac:InvoiceLine>
                <cac:Item>
                    <cbc:Description>Servicio de pruebas</cbc:Description>
                </cac:Item>
            </cac:InvoiceLine>
            <cac:LegalMonetaryTotal>
                <cbc:LineExtensionAmount>1000.00</cbc:LineExtensionAmount>
                <cbc:PayableAmount>1190.00</cbc:PayableAmount>
            </cac:LegalMonetaryTotal>
            <cac:TaxTotal>
                <cbc:TaxAmount>190.00</cbc:TaxAmount>
            </cac:TaxTotal>
        </Invoice>
        """

        xml_path = _write_xml(xml_content)
        self.addCleanup(lambda: os.remove(xml_path))

        procesar_xml(xml_path)

        factura = FacturaXML.objects.get(cufe="123ABC")
        proveedor = Proveedor.objects.get(nit="900123456")

        self.assertEqual(factura.proveedor, proveedor)
        self.assertEqual(factura.descripcion, "Servicio de pruebas")
        self.assertEqual(factura.subtotal, Decimal("1000.00"))
        self.assertEqual(factura.iva, Decimal("190.00"))
        self.assertEqual(factura.total, Decimal("1190.00"))

    def test_procesar_xml_maneja_campos_opcionales(self):
        xml_content = """<?xml version='1.0' encoding='UTF-8'?>
        <Invoice xmlns='urn:oasis:names:specification:ubl:schema:xsd:Invoice-2'
                 xmlns:cac='urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2'
                 xmlns:cbc='urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2'>
            <cbc:UUID>456DEF</cbc:UUID>
            <cbc:IssueDate>2024-02-01</cbc:IssueDate>
            <cac:AccountingSupplierParty>
                <cac:Party>
                    <cac:PartyName>
                        <cbc:Name>Proveedor Incompleto</cbc:Name>
                    </cac:PartyName>
                    <cac:PartyTaxScheme>
                        <cbc:CompanyID>901987654</cbc:CompanyID>
                    </cac:PartyTaxScheme>
                </cac:Party>
            </cac:AccountingSupplierParty>
            <cac:LegalMonetaryTotal>
                <cbc:LineExtensionAmount></cbc:LineExtensionAmount>
            </cac:LegalMonetaryTotal>
        </Invoice>
        """

        xml_path = _write_xml(xml_content)
        self.addCleanup(lambda: os.remove(xml_path))

        procesar_xml(xml_path)

        factura = FacturaXML.objects.get(cufe="456DEF")

        self.assertEqual(factura.descripcion, "")
        self.assertEqual(factura.subtotal, Decimal("0"))
        self.assertEqual(factura.iva, Decimal("0"))
        self.assertEqual(factura.total, Decimal("0"))


class SincronizarEstadoFacturasXLSTests(TestCase):
    def setUp(self):
        self.proveedor = Proveedor.objects.create(
            nit="900555111", nombre="Proveedor Sincronización"
        )

    def test_activa_factura_cuando_xml_existe(self):
        FacturaXML.objects.create(
            cufe="SYNC-1",
            fecha=date(2024, 3, 10),
            descripcion="Factura sincronizada",
            subtotal=Decimal("100.00"),
            iva=Decimal("19.00"),
            total=Decimal("119.00"),
            proveedor=self.proveedor,
        )

        FacturaXLS.objects.create(
            tipo_documento="Factura electrónica",
            cufe="SYNC-1",
            iva=Decimal("19.00"),
            total=Decimal("119.00"),
            activo=False,
        )

        sincronizar_estado_facturas_xls()

        factura_xls = FacturaXLS.objects.get(cufe="SYNC-1")
        self.assertTrue(factura_xls.activo)

    def test_desactiva_factura_cuando_xml_no_existe(self):
        FacturaXLS.objects.create(
            tipo_documento="Factura electrónica",
            cufe="SYNC-2",
            iva=Decimal("0"),
            total=Decimal("0"),
            activo=True,
        )

        sincronizar_estado_facturas_xls()

        factura_xls = FacturaXLS.objects.get(cufe="SYNC-2")
        self.assertFalse(factura_xls.activo)


class DashboardUploadZipTests(TestCase):
    def test_zip_upload_syncs_existing_factura_xls(self):
        FacturaXLS.objects.create(
            tipo_documento="Factura electrónica",
            cufe="ZIP-1",
            iva=Decimal("0"),
            total=Decimal("0"),
            activo=False,
        )

        xml_content = """<?xml version='1.0' encoding='UTF-8'?>
        <Invoice xmlns='urn:oasis:names:specification:ubl:schema:xsd:Invoice-2'
                 xmlns:cac='urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2'
                 xmlns:cbc='urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2'>
            <cbc:UUID>ZIP-1</cbc:UUID>
            <cbc:IssueDate>2024-04-01</cbc:IssueDate>
            <cac:AccountingSupplierParty>
                <cac:Party>
                    <cac:PartyName>
                        <cbc:Name>Proveedor Zip</cbc:Name>
                    </cac:PartyName>
                    <cac:PartyTaxScheme>
                        <cbc:CompanyID>900777333</cbc:CompanyID>
                    </cac:PartyTaxScheme>
                </cac:Party>
            </cac:AccountingSupplierParty>
            <cac:LegalMonetaryTotal>
                <cbc:PayableAmount>100.00</cbc:PayableAmount>
            </cac:LegalMonetaryTotal>
        </Invoice>
        """

        xml_bytes = xml_content.encode("utf-8")
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w") as zf:
            zf.writestr("factura.xml", xml_bytes)
        buffer.seek(0)

        uploaded_zip = SimpleUploadedFile(
            "facturas.zip", buffer.read(), content_type="application/zip"
        )

        response = self.client.post(
            reverse("dashboard"),
            {"upload_zip": "1", "archivo": uploaded_zip},
            format="multipart",
            follow=False,
        )

        self.assertEqual(response.status_code, 302)

        self.assertTrue(FacturaXML.objects.filter(cufe="ZIP-1").exists())
        factura_xls = FacturaXLS.objects.get(cufe="ZIP-1")
        self.assertTrue(factura_xls.activo)


class DashboardFechaExcelTests(TestCase):
    def setUp(self):
        self.proveedor = Proveedor.objects.create(
            nit="901112223", nombre="Proveedor Fecha"
        )

        self.factura_xml = FacturaXML.objects.create(
            cufe="FECHA-1",
            fecha=date(2024, 4, 30),
            descripcion="Factura con fecha",
            subtotal=Decimal("100.00"),
            iva=Decimal("19.00"),
            total=Decimal("119.00"),
            proveedor=self.proveedor,
        )

        FacturaXLS.objects.create(
            tipo_documento="Factura electrónica",
            cufe="FECHA-1",
            folio="123",
            prefijo="PX",
            nit_emisor="901112223",
            nombre_emisor="Proveedor Fecha",
            fecha_documento=date(2024, 5, 2),
            iva=Decimal("19.00"),
            inc=Decimal("0.00"),
            total=Decimal("119.00"),
            activo=True,
        )

    def test_fecha_excel_visible_en_dashboard_y_liquidacion(self):
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)

        contenido = response.content.decode("utf-8")

        # La fecha debe aparecer en la tabla de Excel.
        self.assertIn(">2024-05-02<", contenido)

        # Y también debe serializarse para la liquidación cuando coincide el CUFE.
        self.assertIn('data-fecha="2024-05-02"', contenido)

class DescargarLiquidacionCSVTests(TestCase):
    def setUp(self):
        self.proveedor = Proveedor.objects.create(
            nit="900888777", nombre="Proveedor CSV"
        )

    def _crear_factura_xml(self, cufe: str) -> FacturaXML:
        return FacturaXML.objects.create(
            cufe=cufe,
            fecha=date(2024, 1, 15),
            descripcion="Servicio demo",
            subtotal=Decimal("100.00"),
            iva=Decimal("19.00"),
            total=Decimal("119.00"),
            proveedor=self.proveedor,
        )

    def _crear_factura_xls(
        self,
        cufe: str,
        *,
        fecha_documento: date | None,
    ) -> FacturaXLS:
        return FacturaXLS.objects.create(
            tipo_documento="Factura electrónica",
            cufe=cufe,
            folio="001",
            prefijo="PRF",
            nit_emisor="900888777",
            nombre_emisor="Proveedor CSV",
            fecha_documento=fecha_documento,
            iva=Decimal("19.00"),
            inc=Decimal("0.00"),
            total=Decimal("119.00"),
            activo=True,
        )

    def _obtener_primera_fila(self) -> dict[str, str]:
        response = self.client.get(reverse("descargar_liquidacion"))
        self.assertEqual(response.status_code, 200)
        contenido = response.content.decode("utf-8").splitlines()
        reader = csv.DictReader(contenido)
        return next(reader)

    def test_prefiere_fecha_excel_en_csv(self):
        self._crear_factura_xml("CSV-1")
        self._crear_factura_xls("CSV-1", fecha_documento=date(2024, 2, 5))

        fila = self._obtener_primera_fila()

        self.assertEqual(fila["Fecha"], "2024-02-05")

    def test_no_usa_fecha_xml_si_excel_no_tiene(self):
        self._crear_factura_xml("CSV-2")
        self._crear_factura_xls("CSV-2", fecha_documento=None)

        fila = self._obtener_primera_fila()

        self.assertEqual(fila["Fecha"], "")
