import csv
import json
import os
import tempfile
import zipfile
from datetime import date
from decimal import Decimal
from io import BytesIO
from urllib.parse import quote

import pandas as pd
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from .models import (
    CuentaContable,
    CuentaContableProveedor,
    Empresa,
    FacturaXML,
    FacturaXLS,
    PermisoEmpresa,
    Proveedor,
)
from .views import _extract_fecha_xls, procesar_xml, sincronizar_estado_facturas_xls


class EmpresaTestMixin:
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.empresa = Empresa.objects.create(nombre="GOL", nit="GOL-TEST")
        User = get_user_model()
        cls.usuario = User.objects.create_user(
            username="usuario@example.com",
            email="usuario@example.com",
            password="segura123",
            first_name="Usuario",
            last_name="Demo",
        )
        PermisoEmpresa.objects.create(
            usuario=cls.usuario,
            empresa=cls.empresa,
            es_administrador=True,
        )

    def autenticar(self):
        self.client.force_login(self.usuario)
        session = self.client.session
        session["empresa_actual_id"] = self.empresa.id
        session.save()


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


class ProcesarXMLTests(EmpresaTestMixin, TestCase):
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

        procesar_xml(xml_path, self.empresa)

        factura = FacturaXML.objects.get(cufe="123ABC", empresa=self.empresa)
        proveedor = Proveedor.objects.get(nit="900123456", empresa=self.empresa)

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

        procesar_xml(xml_path, self.empresa)

        factura = FacturaXML.objects.get(cufe="456DEF", empresa=self.empresa)

        self.assertEqual(factura.descripcion, "")
        self.assertEqual(factura.subtotal, Decimal("0"))
        self.assertEqual(factura.iva, Decimal("0"))
        self.assertEqual(factura.total, Decimal("0"))


class SincronizarEstadoFacturasXLSTests(EmpresaTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.proveedor = Proveedor.objects.create(
            empresa=self.empresa,
            nit="900555111",
            nombre="Proveedor Sincronización",
        )

    def test_activa_factura_cuando_xml_existe(self):
        FacturaXML.objects.create(
            empresa=self.empresa,
            cufe="SYNC-1",
            fecha=date(2024, 3, 10),
            descripcion="Factura sincronizada",
            subtotal=Decimal("100.00"),
            iva=Decimal("19.00"),
            total=Decimal("119.00"),
            proveedor=self.proveedor,
        )

        FacturaXLS.objects.create(
            empresa=self.empresa,
            tipo_documento="Factura electrónica",
            cufe="SYNC-1",
            iva=Decimal("19.00"),
            total=Decimal("119.00"),
            activo=False,
        )

        sincronizar_estado_facturas_xls(self.empresa)

        factura_xls = FacturaXLS.objects.get(cufe="SYNC-1", empresa=self.empresa)
        self.assertTrue(factura_xls.activo)

    def test_desactiva_factura_cuando_xml_no_existe(self):
        FacturaXLS.objects.create(
            empresa=self.empresa,
            tipo_documento="Factura electrónica",
            cufe="SYNC-2",
            iva=Decimal("0"),
            total=Decimal("0"),
            activo=True,
        )

        sincronizar_estado_facturas_xls(self.empresa)

        factura_xls = FacturaXLS.objects.get(cufe="SYNC-2", empresa=self.empresa)
        self.assertFalse(factura_xls.activo)


class DashboardUploadZipTests(EmpresaTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.autenticar()

    def test_zip_upload_syncs_existing_factura_xls(self):
        FacturaXLS.objects.create(
            empresa=self.empresa,
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

        self.assertTrue(
            FacturaXML.objects.filter(cufe="ZIP-1", empresa=self.empresa).exists()
        )
        factura_xls = FacturaXLS.objects.get(cufe="ZIP-1", empresa=self.empresa)
        self.assertTrue(factura_xls.activo)


class DashboardFechaExcelTests(EmpresaTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.autenticar()
        self.proveedor = Proveedor.objects.create(
            empresa=self.empresa,
            nit="901112223",
            nombre="Proveedor Fecha",
        )

        self.factura_xml = FacturaXML.objects.create(
            empresa=self.empresa,
            cufe="FECHA-1",
            fecha=date(2024, 4, 30),
            descripcion="Factura con fecha",
            subtotal=Decimal("100.00"),
            iva=Decimal("19.00"),
            total=Decimal("119.00"),
            proveedor=self.proveedor,
        )

        FacturaXLS.objects.create(
            empresa=self.empresa,
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

class LiquidacionTestBase(EmpresaTestMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.proveedor = Proveedor.objects.create(
            empresa=cls.empresa,
            nit="900888777",
            nombre="Proveedor Liquidación",
        )

        cls.cuentas = {
            "SUBTOTAL": CuentaContable.objects.create(
                codigo="2310001000", descripcion="Compras"
            ),
            "IVA": CuentaContable.objects.create(
                codigo="2408001000", descripcion="IVA compras"
            ),
            "INC": CuentaContable.objects.create(
                codigo="231053152007", descripcion="INC"
            ),
            "RETEFUENTE": CuentaContable.objects.create(
                codigo="2365001000", descripcion="ReteFuente"
            ),
            "RETEICA": CuentaContable.objects.create(
                codigo="2368001000", descripcion="ReteICA"
            ),
            "RETEIVA": CuentaContable.objects.create(
                codigo="2367001000", descripcion="ReteIVA"
            ),
            "TOTAL_NETO": CuentaContable.objects.create(
                codigo="2335001000", descripcion="Cuentas por pagar"
            ),
        }

        cls.parametros = {
            "SUBTOTAL": CuentaContableProveedor.objects.create(
                proveedor=cls.proveedor,
                cuenta=cls.cuentas["SUBTOTAL"],
                casilla=CuentaContableProveedor.Casilla.SUBTOTAL,
                naturaleza="D",
            ),
            "IVA": CuentaContableProveedor.objects.create(
                proveedor=cls.proveedor,
                cuenta=cls.cuentas["IVA"],
                casilla=CuentaContableProveedor.Casilla.IVA,
                naturaleza="D",
            ),
            "INC": CuentaContableProveedor.objects.create(
                proveedor=cls.proveedor,
                cuenta=cls.cuentas["INC"],
                casilla=CuentaContableProveedor.Casilla.INC,
                naturaleza="D",
            ),
            "RETEFUENTE": CuentaContableProveedor.objects.create(
                proveedor=cls.proveedor,
                cuenta=cls.cuentas["RETEFUENTE"],
                casilla=CuentaContableProveedor.Casilla.RETEFUENTE,
                naturaleza="C",
                porcentaje=Decimal("4.0000"),
            ),
            "RETEICA": CuentaContableProveedor.objects.create(
                proveedor=cls.proveedor,
                cuenta=cls.cuentas["RETEICA"],
                casilla=CuentaContableProveedor.Casilla.RETEICA,
                naturaleza="C",
                porcentaje=Decimal("9.5000"),
                modo_calculo=CuentaContableProveedor.ModoCalculo.PORCENTAJE,
            ),
            "RETEIVA": CuentaContableProveedor.objects.create(
                proveedor=cls.proveedor,
                cuenta=cls.cuentas["RETEIVA"],
                casilla=CuentaContableProveedor.Casilla.RETEIVA,
                naturaleza="C",
                porcentaje=Decimal("15.0000"),
            ),
            "TOTAL_NETO": CuentaContableProveedor.objects.create(
                proveedor=cls.proveedor,
                cuenta=cls.cuentas["TOTAL_NETO"],
                casilla=CuentaContableProveedor.Casilla.TOTAL_NETO,
                naturaleza="D",
            ),
        }

    def setUp(self):
        super().setUp()
        self.autenticar()
        self.factura_xml = FacturaXML.objects.create(
            empresa=self.empresa,
            cufe="CUFE-LIQ-1",
            fecha=date(2024, 1, 10),
            descripcion="Servicios",
            subtotal=Decimal("100.00"),
            iva=Decimal("19.00"),
            total=Decimal("134.50"),
            proveedor=self.proveedor,
        )
        self.factura_xls = FacturaXLS.objects.create(
            empresa=self.empresa,
            tipo_documento="Factura electrónica",
            cufe="CUFE-LIQ-1",
            folio="001",
            prefijo="PRF",
            nit_emisor=self.proveedor.nit,
            nombre_emisor=self.proveedor.nombre,
            fecha_documento=date(2024, 1, 12),
            iva=Decimal("19.00"),
            inc=Decimal("0.00"),
            total=Decimal("134.50"),
            activo=True,
        )

    @staticmethod
    def _format_decimal(value: Decimal, places: int = 2) -> str:
        quantum = Decimal(1).scaleb(-places)
        return f"{value.quantize(quantum)}"

    def build_fila_payload(self, **overrides) -> dict:
        subtotal = Decimal("100.00")
        iva = Decimal("19.00")
        inc = Decimal("0.00")
        retefuente = subtotal * Decimal("4.0000") / Decimal("100")
        reteica = subtotal * Decimal("9.5000") / Decimal("100")
        reteiva = subtotal * Decimal("15.0000") / Decimal("100")
        total_neto = subtotal + iva + inc - retefuente - reteica - reteiva

        fila = {
            "factura_id": self.factura_xls.id,
            "proveedor_id": self.proveedor.id,
            "tipo_documento": self.factura_xls.tipo_documento,
            "cufe": self.factura_xls.cufe,
            "nit": self.proveedor.nit,
            "proveedor": self.proveedor.nombre,
            "fecha": "2024-01-12",
            "descripcion": "Servicios",
            "prefijo_folio": "PRF-001",
            "importes": {
                "subtotal": self._format_decimal(subtotal),
                "iva": self._format_decimal(iva),
                "inc": self._format_decimal(inc),
                "retefuente": self._format_decimal(retefuente),
                "reteica": self._format_decimal(reteica),
                "reteiva": self._format_decimal(reteiva),
                "total_neto": self._format_decimal(total_neto),
            },
            "cuentas": {
                "subtotal": self.parametros["SUBTOTAL"].id,
                "iva": self.parametros["IVA"].id,
                "inc": self.parametros["INC"].id,
                "retefuente": self.parametros["RETEFUENTE"].id,
                "reteica": self.parametros["RETEICA"].id,
                "reteiva": self.parametros["RETEIVA"].id,
                "total_neto": self.parametros["TOTAL_NETO"].id,
            },
            "porcentajes": {
                "retefuente": self._format_decimal(Decimal("4.0000"), 4),
                "reteica": self._format_decimal(Decimal("9.5000"), 4),
                "reteiva": self._format_decimal(Decimal("15.0000"), 4),
            },
        }
        for key, value in overrides.items():
            fila[key] = value
        return fila


class LiquidacionCatalogosViewTests(LiquidacionTestBase):
    def test_devuelve_catalogos_filtrados(self):
        url = reverse("liquidacion_catalogos", args=[self.proveedor.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("catalogos", data)
        catalogos = data["catalogos"]
        self.assertEqual(len(catalogos["subtotales"]), 1)
        self.assertEqual(
            catalogos["subtotales"][0]["codigo"], self.cuentas["SUBTOTAL"].codigo
        )
        self.assertEqual(len(catalogos["retefuente"]), 1)
        self.assertEqual(
            catalogos["retefuente"][0]["porcentaje"],
            self._format_decimal(Decimal("4.0000"), 4),
        )

    def test_proveedor_inexistente(self):
        url = reverse("liquidacion_catalogos", args=[9999])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)


class LiquidacionValidacionTests(LiquidacionTestBase):
    def test_validacion_exitosa(self):
        fila = self.build_fila_payload()
        response = self.client.post(
            reverse("liquidacion_validar"),
            data=json.dumps({"filas": [fila]}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["valido"])
        self.assertEqual(len(data["filas"]), 1)
        resultado = data["filas"][0]
        self.assertEqual(
            resultado["cuentas"]["subtotal"], self.parametros["SUBTOTAL"].id
        )
        self.assertEqual(resultado["porcentajes"]["retefuente"], "4.0000")
        self.assertTrue(resultado["listo"])

    def test_error_por_cuenta_obligatoria(self):
        fila = self.build_fila_payload()
        fila["cuentas"]["subtotal"] = None
        response = self.client.post(
            reverse("liquidacion_validar"),
            data=json.dumps({"filas": [fila]}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data.get("valido", False))
        mensajes = " ".join(error["mensaje"] for error in data["errores"])
        self.assertIn("El campo ‘Cuenta contable’ es obligatorio", mensajes)
        self.assertFalse(data["filas"][0]["listo"])

    def test_error_por_cuenta_de_otro_proveedor(self):
        otro_proveedor = Proveedor.objects.create(
            empresa=self.empresa, nit="800123456", nombre="Proveedor 2"
        )
        cuenta_otro = CuentaContable.objects.create(
            codigo="2310999999", descripcion="Subtotal otro"
        )
        parametro_otro = CuentaContableProveedor.objects.create(
            proveedor=otro_proveedor,
            cuenta=cuenta_otro,
            casilla=CuentaContableProveedor.Casilla.SUBTOTAL,
            naturaleza="D",
        )
        fila = self.build_fila_payload()
        fila["cuentas"]["subtotal"] = parametro_otro.id
        response = self.client.post(
            reverse("liquidacion_validar"),
            data=json.dumps({"filas": [fila]}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        data = response.json()
        mensajes = " ".join(error["mensaje"] for error in data["errores"])
        self.assertIn("La cuenta seleccionada no pertenece al proveedor", mensajes)

    def test_validacion_sin_parametrizacion_retencion_devuelve_na(self):
        self.parametros["RETEFUENTE"].delete()
        fila = self.build_fila_payload()
        fila["cuentas"]["retefuente"] = None
        response = self.client.post(
            reverse("liquidacion_validar"),
            data=json.dumps({"filas": [fila]}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["valido"])
        self.assertEqual(len(data["errores"]), 0)
        resultado = data["filas"][0]
        self.assertIsNone(resultado["cuentas"].get("retefuente"))
        self.assertTrue(resultado["listo"])

    def test_validacion_sin_parametrizacion_valor_fijo_devuelve_na(self):
        self.parametros["IVA"].delete()
        fila = self.build_fila_payload()
        fila["cuentas"]["iva"] = None
        response = self.client.post(
            reverse("liquidacion_validar"),
            data=json.dumps({"filas": [fila]}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["valido"])
        self.assertEqual(len(data["errores"]), 0)
        resultado = data["filas"][0]
        self.assertIsNone(resultado["cuentas"].get("iva"))
        self.assertTrue(resultado["listo"])

    def test_validacion_total_neto_sin_parametrizacion_devuelve_na(self):
        self.parametros["TOTAL_NETO"].delete()
        fila = self.build_fila_payload()
        fila["cuentas"]["total_neto"] = None
        response = self.client.post(
            reverse("liquidacion_validar"),
            data=json.dumps({"filas": [fila]}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["valido"])
        self.assertEqual(len(data["errores"]), 0)
        resultado = data["filas"][0]
        self.assertIsNone(resultado["cuentas"].get("total_neto"))
        self.assertTrue(resultado["listo"])


class LiquidacionExportarTests(LiquidacionTestBase):
    def test_exporta_csv_con_cuentas(self):
        fila = self.build_fila_payload()
        payload = quote(json.dumps({"filas": [fila]}))
        url = reverse("liquidacion_exportar") + f"?formato=csv&payload={payload}"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        contenido = response.content.decode("utf-8").splitlines()
        reader = csv.DictReader(contenido)
        self.assertEqual(len(reader.fieldnames), 24)
        fila_csv = next(reader)

        self.assertEqual(
            fila_csv["Sub total – Cuenta contable"],
            self.cuentas["SUBTOTAL"].codigo,
        )
        self.assertEqual(fila_csv["ReteFuente – Cuenta contable"], self.cuentas["RETEFUENTE"].codigo)
        self.assertEqual(fila_csv["ReteFuente (%)"], "4.0000")
        self.assertEqual(fila_csv["Tipo documento"], self.factura_xls.tipo_documento)
        self.assertEqual(fila_csv["CUFE/CUDE"], self.factura_xls.cufe)
        self.assertEqual(fila_csv["ReteFuente (valor)"], "-4.00")
        self.assertEqual(fila_csv["Total neto"], "90.50")
        self.assertEqual(
            fila_csv["Total neto – Cuenta contable"],
            self.cuentas["TOTAL_NETO"].codigo,
        )
        self.assertEqual(fila_csv["INC – Cuenta contable"], "N/A")

    def test_exporta_csv_valor_cero_generar_na(self):
        fila = self.build_fila_payload()
        fila["importes"]["iva"] = self._format_decimal(Decimal("0.00"))
        payload = quote(json.dumps({"filas": [fila]}))
        url = reverse("liquidacion_exportar") + f"?formato=csv&payload={payload}"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        contenido = response.content.decode("utf-8").splitlines()
        reader = csv.DictReader(contenido)
        fila_csv = next(reader)

        self.assertEqual(fila_csv["IVA – Cuenta contable"], "N/A")

    def test_exporta_csv_campo_vacio_generar_na(self):
        fila = self.build_fila_payload()
        fila["cuentas"]["inc"] = None
        payload = quote(json.dumps({"filas": [fila]}))
        url = reverse("liquidacion_exportar") + f"?formato=csv&payload={payload}"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        contenido = response.content.decode("utf-8").splitlines()
        reader = csv.DictReader(contenido)
        fila_csv = next(reader)

        self.assertEqual(fila_csv["INC – Cuenta contable"], "N/A")

    def test_exporta_csv_total_neto_sin_parametrizacion_generar_na(self):
        self.parametros["TOTAL_NETO"].delete()
        fila = self.build_fila_payload()
        fila["cuentas"]["total_neto"] = None
        payload = quote(json.dumps({"filas": [fila]}))
        url = reverse("liquidacion_exportar") + f"?formato=csv&payload={payload}"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        contenido = response.content.decode("utf-8").splitlines()
        reader = csv.DictReader(contenido)
        fila_csv = next(reader)

        self.assertEqual(fila_csv["Total neto – Cuenta contable"], "N/A")


class LogoutFlowTests(EmpresaTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.autenticar()

    def test_logout_via_post(self):
        response = self.client.post(reverse("logout"))
        self.assertRedirects(response, reverse("login"), fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_seleccionar_empresa_sin_permisos_redirige_a_login(self):
        PermisoEmpresa.objects.filter(usuario=self.usuario).delete()
        response = self.client.get(reverse("seleccionar_empresa"))
        self.assertRedirects(response, reverse("login"))
        self.assertNotIn("_auth_user_id", self.client.session)
