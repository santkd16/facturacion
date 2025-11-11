# Scripts SQL de parametrización

Este directorio agrupa consultas listas para ejecutarse directamente sobre la base de datos de facturación. Cada script está pensado para cargarse con `psql` o el cliente que utilices contra la base de datos PostgreSQL configurada en Django.

## `parametrizaciones_proveedores.sql`

* Inserta (o actualiza) el catálogo global de `procesador_cuentacontable` con los códigos suministrados.
* Crea las parametrizaciones de `procesador_cuentacontableproveedor` filtrando por NIT y asignando la casilla, naturaleza, porcentaje y modo de cálculo correctos según las reglas de liquidación.
* Los porcentajes de retención se derivan de la descripción de cada cuenta (por ejemplo `4%`, `0.966%`, `15%`).
* Si una cuenta no tiene porcentaje asociado (subtotales, IVA, INC, total neto) el script deja el campo en `NULL` y marca la naturaleza conforme a los datos suministrados (Débito/Crédito).

### Ejecución

```bash
psql "$DATABASE_URL" -f docs/sql/parametrizaciones_proveedores.sql
```

El script usa `ON CONFLICT` para que las cuentas existentes se actualicen sin duplicados. Solo inserta parametrizaciones para proveedores cuyo NIT ya esté registrado en `procesador_proveedor`; si algún NIT no existe la fila se omite y podrás detectar el caso revisando el conteo de filas afectadas que muestra `psql`.

> **Nota:** antes de ejecutar, asegúrate de tener respaldo de la base de datos en caso de necesitar revertir los cambios.
