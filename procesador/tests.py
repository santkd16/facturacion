import os
import tempfile
from datetime import date
from decimal import Decimal

from django.test import TestCase

from .models import FacturaXML, FacturaXLS, Proveedor
from .views import procesar_xml, sincronizar_estado_facturas_xls


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
