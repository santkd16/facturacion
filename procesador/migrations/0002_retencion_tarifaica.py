from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("procesador", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="TarifaICA",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("valor", models.DecimalField(decimal_places=2, max_digits=5)),
                ("descripcion", models.CharField(blank=True, default="", max_length=100)),
            ],
            options={
                "unique_together": {("valor", "descripcion")},
            },
        ),
        migrations.CreateModel(
            name="Retencion",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("porcentaje", models.DecimalField(decimal_places=2, max_digits=5)),
                ("cuenta_contable", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="procesador.cuentacontable")),
                ("proveedor", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="retenciones", to="procesador.proveedor")),
            ],
            options={
                "unique_together": {("proveedor", "porcentaje")},
            },
        ),
    ]
