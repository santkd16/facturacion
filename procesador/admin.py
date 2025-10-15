
from django.contrib import admin
from .models import Proveedor, FacturaXML, FacturaXLS, CuentaContable, Retencion, TarifaICA

@admin.register(Proveedor)
class ProveedorAdmin(admin.ModelAdmin):
    list_display = ("nombre", "nit")
    search_fields = ("nombre", "nit")

@admin.register(FacturaXML)
class FacturaXMLAdmin(admin.ModelAdmin):
    list_display = ("cufe", "fecha", "proveedor", "subtotal", "iva", "total")
    list_filter = ("fecha", "proveedor")

@admin.register(FacturaXLS)
class FacturaXLSAdmin(admin.ModelAdmin):
    list_display = ("tipo_documento", "cufe", "nit_emisor", "nombre_emisor", "iva", "inc", "total", "activo")
    search_fields = ("cufe", "nit_emisor", "nombre_emisor")
    list_filter = ("activo", "tipo_documento")

@admin.register(CuentaContable)
class CuentaContableAdmin(admin.ModelAdmin):
    list_display = ("codigo", "descripcion")
    search_fields = ("codigo", "descripcion")

@admin.register(Retencion)
class RetencionAdmin(admin.ModelAdmin):
    list_display = ("proveedor", "porcentaje", "cuenta_contable")
    list_filter = ("proveedor",)

@admin.register(TarifaICA)
class TarifaICAAdmin(admin.ModelAdmin):
    list_display = ("valor", "descripcion")

admin.site.register(Proveedor)
admin.site.register(FacturaXML)
admin.site.register(FacturaXLS)
admin.site.register(CuentaContable)