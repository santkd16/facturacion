from django.urls import path
from . import views


urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path(
        "seleccionar-empresa/",
        views.seleccionar_empresa,
        name="seleccionar_empresa",
    ),
    path(
        "liquidacion/<int:proveedor_id>/catalogos/",
        views.liquidacion_catalogos,
        name="liquidacion_catalogos",
    ),
    path(
        "liquidacion/validar/",
        views.liquidacion_validar,
        name="liquidacion_validar",
    ),
    path(
        "liquidacion/exportar/",
        views.liquidacion_exportar,
        name="liquidacion_exportar",
    ),
]