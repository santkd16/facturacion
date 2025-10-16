from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [
        ("procesador", "0002_retencion_tarifaica"),
    ]

    operations = [
        migrations.AddField(
            model_name="facturaxls",
            name="fecha_documento",
            field=models.DateField(blank=True, null=True),
        ),
    ]
