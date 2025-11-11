from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("procesador", "0005_empresa_permisos"),
    ]

    operations = [
        migrations.CreateModel(
            name="CuentaContableProveedor",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("casilla", models.CharField(choices=[
                    ("SUBTOTAL", "Sub total"),
                    ("IVA", "IVA"),
                    ("INC", "INC"),
                    ("RETEFUENTE", "ReteFuente"),
                    ("RETEICA", "ReteICA"),
                    ("RETEIVA", "ReteIva"),
                    ("TOTAL_NETO", "Total neto"),
                ], max_length=20)),
                ("naturaleza", models.CharField(choices=[("D", "Débito"), ("C", "Crédito")], max_length=1)),
                ("porcentaje", models.DecimalField(blank=True, decimal_places=4, max_digits=9, null=True)),
                ("modo_calculo", models.CharField(blank=True, choices=[("PORCENTAJE", "Porcentaje"), ("PORMIL", "Por mil")], max_length=10)),
                ("ayuda", models.CharField(blank=True, default="", max_length=255)),
                ("activo", models.BooleanField(default=True)),
                ("creado_en", models.DateTimeField(auto_now_add=True)),
                ("actualizado_en", models.DateTimeField(auto_now=True)),
                ("cuenta", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="parametrizaciones", to="procesador.cuentacontable")),
                ("proveedor", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="catalogo_cuentas", to="procesador.proveedor")),
            ],
            options={
                "verbose_name": "Parametrización de cuenta",
                "verbose_name_plural": "Parametrizaciones de cuentas",
                "unique_together": {("proveedor", "casilla", "cuenta")},
            },
        ),
    ]
