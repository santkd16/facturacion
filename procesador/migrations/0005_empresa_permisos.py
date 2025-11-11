# Generated manually to introduce gestión multiempresa
from django.conf import settings
from django.db import migrations, models


def crear_empresa_por_defecto(apps, schema_editor):
    Empresa = apps.get_model('procesador', 'Empresa')
    Proveedor = apps.get_model('procesador', 'Proveedor')
    FacturaXML = apps.get_model('procesador', 'FacturaXML')
    FacturaXLS = apps.get_model('procesador', 'FacturaXLS')

    empresa, _ = Empresa.objects.get_or_create(
        nombre='GOL',
        defaults={'nit': 'GOL-DEFAULT', 'activo': True},
    )
    Proveedor.objects.filter(empresa__isnull=True).update(empresa=empresa)
    FacturaXML.objects.filter(empresa__isnull=True).update(empresa=empresa)
    FacturaXLS.objects.filter(empresa__isnull=True).update(empresa=empresa)


def revertir_empresa_por_defecto(apps, schema_editor):
    # No revertimos la asignación para evitar perder relaciones
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('procesador', '0004_merge_20251016_1625'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Empresa',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nombre', models.CharField(max_length=255, unique=True)),
                ('nit', models.CharField(max_length=50, unique=True)),
                ('activo', models.BooleanField(default=True)),
            ],
            options={
                'verbose_name': 'Empresa',
                'verbose_name_plural': 'Empresas',
            },
        ),
        migrations.CreateModel(
            name='PermisoEmpresa',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('es_administrador', models.BooleanField(default=False)),
                ('empresa', models.ForeignKey(on_delete=models.CASCADE, related_name='permisos', to='procesador.empresa')),
                ('usuario', models.ForeignKey(on_delete=models.CASCADE, related_name='permisos_empresas', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Permiso de empresa',
                'verbose_name_plural': 'Permisos de empresas',
                'unique_together': {('usuario', 'empresa')},
            },
        ),
        migrations.AlterField(
            model_name='proveedor',
            name='nit',
            field=models.CharField(max_length=50),
        ),
        migrations.AddField(
            model_name='proveedor',
            name='empresa',
            field=models.ForeignKey(null=True, on_delete=models.CASCADE, related_name='proveedores', to='procesador.empresa'),
        ),
        migrations.AlterField(
            model_name='facturaxml',
            name='cufe',
            field=models.CharField(max_length=255),
        ),
        migrations.AddField(
            model_name='facturaxml',
            name='empresa',
            field=models.ForeignKey(null=True, on_delete=models.CASCADE, related_name='facturas_xml', to='procesador.empresa'),
        ),
        migrations.AlterField(
            model_name='facturaxls',
            name='cufe',
            field=models.CharField(max_length=255),
        ),
        migrations.AddField(
            model_name='facturaxls',
            name='empresa',
            field=models.ForeignKey(null=True, on_delete=models.CASCADE, related_name='facturas_xls', to='procesador.empresa'),
        ),
        migrations.AlterUniqueTogether(
            name='proveedor',
            unique_together={('empresa', 'nit')},
        ),
        migrations.AlterUniqueTogether(
            name='facturaxml',
            unique_together={('empresa', 'cufe')},
        ),
        migrations.AlterUniqueTogether(
            name='facturaxls',
            unique_together={('empresa', 'cufe')},
        ),
        migrations.RunPython(crear_empresa_por_defecto, revertir_empresa_por_defecto),
        migrations.AlterField(
            model_name='proveedor',
            name='empresa',
            field=models.ForeignKey(on_delete=models.CASCADE, related_name='proveedores', to='procesador.empresa'),
        ),
        migrations.AlterField(
            model_name='facturaxml',
            name='empresa',
            field=models.ForeignKey(on_delete=models.CASCADE, related_name='facturas_xml', to='procesador.empresa'),
        ),
        migrations.AlterField(
            model_name='facturaxls',
            name='empresa',
            field=models.ForeignKey(on_delete=models.CASCADE, related_name='facturas_xls', to='procesador.empresa'),
        ),
    ]
