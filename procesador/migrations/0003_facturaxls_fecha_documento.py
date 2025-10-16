from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [
        ("procesador", "0002_retencion_tarifaica"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="facturaxls",
                    name="fecha_documento",
                    field=models.DateField(blank=True, null=True),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql=(
                        "ALTER TABLE IF EXISTS procesador_facturaxls "
                        "ADD COLUMN IF NOT EXISTS fecha_documento date"
                    ),
                    reverse_sql=(
                        "ALTER TABLE IF EXISTS procesador_facturaxls "
                        "DROP COLUMN IF EXISTS fecha_documento"
                    ),
                )
            ],
        )
    ]
