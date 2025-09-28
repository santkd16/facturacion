from django.contrib import admin
from .models import Proveedor, FacturaXML, FacturaXLS, CuentaContable

admin.site.register(Proveedor)
admin.site.register(FacturaXML)
admin.site.register(FacturaXLS)
admin.site.register(CuentaContable)
