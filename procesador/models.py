from django.db import models

class Proveedor(models.Model):
    nit = models.CharField(max_length=50, unique=True)
    nombre = models.CharField(max_length=255)

    def __str__(self):
        return f"{self.nombre} ({self.nit})"


class FacturaXML(models.Model):
    cufe = models.CharField(max_length=255, unique=True)
    fecha = models.DateField()
    descripcion = models.TextField()
    subtotal = models.DecimalField(max_digits=12, decimal_places=2)
    iva = models.DecimalField(max_digits=12, decimal_places=2)
    total = models.DecimalField(max_digits=12, decimal_places=2)
    proveedor = models.ForeignKey(Proveedor, on_delete=models.CASCADE)

    def __str__(self):
        return f"XML {self.cufe} - {self.proveedor.nombre}"


class FacturaXLS(models.Model):
    tipo_documento = models.CharField(max_length=100)
    cufe = models.CharField(max_length=255, unique=True)
    folio = models.CharField(max_length=100, blank=True, null=True)
    prefijo = models.CharField(max_length=50, blank=True, null=True)

    # 🔹 Corregidos a EMISOR
    nit_emisor = models.CharField(max_length=50, blank=True, null=True)
    nombre_emisor = models.CharField(max_length=255, blank=True, null=True)

    iva = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    inc = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    activo = models.BooleanField(default=False)  # si existe XML

    def __str__(self):
        return f"XLS {self.cufe} - {self.tipo_documento}"

class CuentaContable(models.Model):
    codigo = models.CharField(max_length=20, unique=True)
    descripcion = models.CharField(max_length=255)

    def __str__(self):
        return f"{self.codigo} - {self.descripcion}"

# --- NUEVO: Retenciones y tarifas ICA ---
class Retencion(models.Model):
    proveedor = models.ForeignKey(Proveedor, on_delete=models.CASCADE, related_name="retenciones")
    porcentaje = models.DecimalField(max_digits=5, decimal_places=2)  # ej: 2.50 = 2.5%
    cuenta_contable = models.ForeignKey(CuentaContable, on_delete=models.PROTECT)

    class Meta:
        unique_together = ("proveedor", "porcentaje")

    def __str__(self):
        return f"RF {self.porcentaje}% - {self.proveedor.nombre}"

class TarifaICA(models.Model):
    valor = models.DecimalField(max_digits=5, decimal_places=2)  # ej: 8.66
    descripcion = models.CharField(max_length=100, blank=True, default="")

    class Meta:
        unique_together = ("valor", "descripcion")

    def __str__(self):
        return f"ICA {self.valor}% {self.descripcion}".strip()
