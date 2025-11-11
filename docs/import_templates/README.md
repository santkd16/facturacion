# Plantillas de carga masiva de cuentas contables

Este directorio contiene archivos CSV listos para cargarse en la base de datos
según los modelos `CuentaContable` y `CuentaContableProveedor`.

## `cuentas_contables.csv`

Columnas:

1. `codigo`: Código único de la cuenta contable.
2. `descripcion`: Descripción legible de la cuenta.

Cargue primero este archivo para garantizar que todas las cuentas existan en el
catálogo global.

## `cuentas_contables_proveedor.csv`

Columnas:

1. `nit_proveedor`: NIT del proveedor parametrizado.
2. `codigo_cuenta`: Código de la cuenta definida en el archivo anterior.
3. `casilla`: Casilla del formulario de liquidación a la que aplica la cuenta.
4. `naturaleza`: Naturaleza contable esperada (`D` = débito, `C` = crédito).
5. `porcentaje`: Tarifa asociada (solo para retenciones). Usar punto como separador decimal.
6. `modo_calculo`: `PORCENTAJE` o `PORMIL` (vacío si no aplica).
7. `ayuda`: Texto de ayuda mostrado en la UI (se usa la descripción original).
8. `activo`: `1` para activo, `0` para inactivo.

Los archivos ya incluyen los datos entregados para la empresa GOL, con los
porcentajes prellenados para ReteFuente, ReteICA y ReteIVA.

> **Nota:** Si se agregan nuevos proveedores o cuentas, respete las mismas
> columnas y formatos. Para cuentas de ReteICA que trabajen en por mil,
> indique `PORMIL` en `modo_calculo` y escriba el valor exacto en `porcentaje`.
