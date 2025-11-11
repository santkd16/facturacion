from django.conf import settings
from django.db import models


class Empresa(models.Model):
    nombre = models.CharField(max_length=255, unique=True)
    nit = models.CharField(max_length=50, unique=True)
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Empresa"
        verbose_name_plural = "Empresas"

    def __str__(self) -> str:
        estado = " (inactiva)" if not self.activo else ""
        return f"{self.nombre} - {self.nit}{estado}"


class PermisoEmpresa(models.Model):
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="permisos_empresas",
    )
    empresa = models.ForeignKey(
        Empresa, on_delete=models.CASCADE, related_name="permisos"
    )
    es_administrador = models.BooleanField(default=False)

    class Meta:
        unique_together = ("usuario", "empresa")
        verbose_name = "Permiso de empresa"
        verbose_name_plural = "Permisos de empresas"

    def __str__(self) -> str:
        rol = "Administrador" if self.es_administrador else "Usuario"
        return f"{self.usuario} - {self.empresa.nombre} ({rol})"


class Proveedor(models.Model):
    empresa = models.ForeignKey(
        Empresa, on_delete=models.CASCADE, related_name="proveedores"
    )
    nit = models.CharField(max_length=50)
    nombre = models.CharField(max_length=255)

    class Meta:
        unique_together = ("empresa", "nit")

    def __str__(self) -> str:
        return f"{self.nombre} ({self.nit})"


class FacturaXML(models.Model):
    empresa = models.ForeignKey(
        Empresa, on_delete=models.CASCADE, related_name="facturas_xml"
    )
    cufe = models.CharField(max_length=255)
    fecha = models.DateField()
    descripcion = models.TextField()
    subtotal = models.DecimalField(max_digits=12, decimal_places=2)
    iva = models.DecimalField(max_digits=12, decimal_places=2)
    total = models.DecimalField(max_digits=12, decimal_places=2)
    proveedor = models.ForeignKey(Proveedor, on_delete=models.CASCADE)

    class Meta:
        unique_together = ("empresa", "cufe")

    def __str__(self) -> str:
        return f"XML {self.cufe} - {self.proveedor.nombre}"


class FacturaXLS(models.Model):
    empresa = models.ForeignKey(
        Empresa, on_delete=models.CASCADE, related_name="facturas_xls"
    )
    tipo_documento = models.CharField(max_length=100)
    cufe = models.CharField(max_length=255)
    folio = models.CharField(max_length=100, blank=True, null=True)
    prefijo = models.CharField(max_length=50, blank=True, null=True)
    nit_emisor = models.CharField(max_length=50, blank=True, null=True)
    nombre_emisor = models.CharField(max_length=255, blank=True, null=True)
    fecha_documento = models.DateField(blank=True, null=True)
    iva = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    inc = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    activo = models.BooleanField(default=False)

    class Meta:
        unique_together = ("empresa", "cufe")

    def __str__(self) -> str:
        return f"XLS {self.cufe} - {self.tipo_documento}"


class CuentaContable(models.Model):
    codigo = models.CharField(max_length=20, unique=True)
    descripcion = models.CharField(max_length=255)

    def __str__(self) -> str:
        return f"{self.codigo} - {self.descripcion}"


class CuentaContableProveedor(models.Model):
    class Casilla(models.TextChoices):
        SUBTOTAL = "SUBTOTAL", "Sub total"
        IVA = "IVA", "IVA"
        INC = "INC", "INC"
        RETEFUENTE = "RETEFUENTE", "ReteFuente"
        RETEICA = "RETEICA", "ReteICA"
        RETEIVA = "RETEIVA", "ReteIva"
        TOTAL_NETO = "TOTAL_NETO", "Total neto"

    class ModoCalculo(models.TextChoices):
        PORCENTAJE = "PORCENTAJE", "Porcentaje"
        PORMIL = "PORMIL", "Por mil"

    proveedor = models.ForeignKey(
        Proveedor, on_delete=models.CASCADE, related_name="catalogo_cuentas"
    )
    cuenta = models.ForeignKey(
        CuentaContable, on_delete=models.PROTECT, related_name="parametrizaciones"
    )
    casilla = models.CharField(max_length=20, choices=Casilla.choices)
    naturaleza = models.CharField(
        max_length=1,
        choices=(
            ("D", "Débito"),
            ("C", "Crédito"),
        ),
    )
    porcentaje = models.DecimalField(
        max_digits=9, decimal_places=4, null=True, blank=True
    )
    modo_calculo = models.CharField(
        max_length=10,
        choices=ModoCalculo.choices,
        blank=True,
    )
    ayuda = models.CharField(max_length=255, blank=True, default="")
    activo = models.BooleanField(default=True)
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("proveedor", "casilla", "cuenta")
        verbose_name = "Parametrización de cuenta"
        verbose_name_plural = "Parametrizaciones de cuentas"

    def __str__(self) -> str:
        return (
            f"{self.proveedor.nombre} - {self.get_casilla_display()} - "
            f"{self.cuenta.codigo} ({self.get_naturaleza_display()})"
        )

    @property
    def porcentaje_display(self) -> str:
        if self.porcentaje is None:
            return ""
        return f"{self.porcentaje.normalize()}"
