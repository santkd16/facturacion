from django.urls import path
from . import views


urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path(
        "descargar-liquidacion/",
        views.descargar_liquidacion_csv,
        name="descargar_liquidacion",
    ),
]