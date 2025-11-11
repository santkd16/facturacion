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
        "descargar-liquidacion/",
        views.descargar_liquidacion_csv,
        name="descargar_liquidacion",
    ),
]