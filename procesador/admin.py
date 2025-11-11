from django.contrib import admin
from .models import (
    CuentaContable,
    CuentaContableProveedor,
    Empresa,
    FacturaXML,
    FacturaXLS,
    PermisoEmpresa,
    Proveedor,
)


@admin.register(Empresa)
class EmpresaAdmin(admin.ModelAdmin):
    list_display = ("nombre", "nit", "activo")
    list_filter = ("activo",)
    search_fields = ("nombre", "nit")


@admin.register(PermisoEmpresa)
class PermisoEmpresaAdmin(admin.ModelAdmin):
    list_display = ("usuario", "empresa", "es_administrador")
    list_filter = ("empresa", "es_administrador")
    search_fields = ("usuario__username", "usuario__email", "empresa__nombre")


@admin.register(Proveedor)
class ProveedorAdmin(admin.ModelAdmin):
    list_display = ("nombre", "nit", "empresa")
    list_filter = ("empresa",)
    search_fields = ("nombre", "nit")


@admin.register(FacturaXML)
class FacturaXMLAdmin(admin.ModelAdmin):
    list_display = (
        "cufe",
        "fecha",
        "proveedor",
        "empresa",
        "subtotal",
        "iva",
        "total",
    )
    list_filter = ("fecha", "proveedor", "empresa")


@admin.register(FacturaXLS)
class FacturaXLSAdmin(admin.ModelAdmin):
    list_display = (
        "tipo_documento",
        "cufe",
        "nit_emisor",
        "nombre_emisor",
        "empresa",
        "iva",
        "inc",
        "total",
        "activo",
    )
    search_fields = ("cufe", "nit_emisor", "nombre_emisor")
    list_filter = ("activo", "tipo_documento", "empresa")


@admin.register(CuentaContable)
class CuentaContableAdmin(admin.ModelAdmin):
    list_display = ("codigo", "descripcion")
    search_fields = ("codigo", "descripcion")


@admin.register(CuentaContableProveedor)
class CuentaContableProveedorAdmin(admin.ModelAdmin):
    list_display = (
        "proveedor",
        "casilla",
        "cuenta",
        "naturaleza",
        "porcentaje",
        "modo_calculo",
        "activo",
    )
    list_filter = (
        "proveedor__empresa",
        "proveedor",
        "casilla",
        "naturaleza",
        "modo_calculo",
        "activo",
    )
    search_fields = (
        "proveedor__nombre",
        "proveedor__nit",
        "cuenta__codigo",
        "cuenta__descripcion",
    )
    autocomplete_fields = ("proveedor", "cuenta")