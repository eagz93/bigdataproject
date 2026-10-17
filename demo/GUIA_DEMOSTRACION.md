# Recorrido operativo con información guardada

La aplicación utiliza la **base operativa actual** y conserva sus 436 SKU. Por decisión expresa del usuario, los movimientos preparados se guardaron como registros ordinarios, sin etiquetas ni una categoría separada. Esta es una **demostración preparada**: sus cantidades, aprobaciones y métricas sirven para comprobar funciones; no acreditan consumo, entregas, órdenes comerciales ni resultados de negocio observados.

## Recorrido rápido

1. Abra `http://localhost:8501` con su cuenta autorizada; no hay contraseñas en estos entregables.
2. En **Plan y aprobación**, revise las recomendaciones y descargue el CSV. Existen tres aprobaciones guardadas de `2026-W42`: SKU `101091` (1 caja), `10850` (1) y `11011346` (40). La aprobación no crea una orden externa ni añade tránsito.
3. En **Consumo** y **Recepciones**, consulte las tablas de registros guardados. Los editores superiores son formularios, no el historial.
4. Cargue uno de los archivos de consumo y uno de recepciones indicados abajo, siguiendo las precauciones de la sección siguiente.
5. En **Control piloto**, consulte las dos semanas guardadas y el estado habilitado. En **Auditoría**, revise los movimientos, aprobaciones y la reanudación; descargue el CSV.

Las tablas de historial requieren que se despliegue la versión actualizada de `app.py` y `operations_store.py`. Esta guía no supone que un contenedor anterior se haya reconstruido automáticamente.

## Dos archivos para cargar en vivo

| Pestaña | CSV | Alternativa Excel equivalente |
|---|---|---|
| Consumo | `consumo_2026-W42.csv` | `consumo_2026-W42.xlsx` |
| Recepciones | `recepciones_2026-W42.csv` | `recepciones_2026-W42.xlsx` |

Elija **CSV o Excel**, no ambos como si fueran lotes adicionales. Los cuatro archivos contienen los mismos cuatro SKU y la semana explícita `2026-W42` (12–18 de octubre de 2026). Las cantidades están expresadas en las unidades del inventario, no en cajas adicionales. Recepciones confirma tránsito ya existente; **no incorpora nuevos pedidos en tránsito**.

### Carga segura y repetición

1. Use Administración o CEDI. Compras puede aprobar; Consulta no puede modificar.
2. Antes de importar, revise el historial semanal. Los archivos son una **instantánea semanal completa por tipo**, no incrementos. Al importar, cualquier SKU previamente guardado en esa semana y tipo que falte en el archivo se reemplaza por cero y se revierte su efecto.
3. Estos archivos corresponden exactamente al estado preparado descrito abajo: tres SKU ya guardados y un cuarto pendiente para la carga en vivo. No omiten ningún registro de consumo o recepción existente al preparar la entrega.
4. Si alguien incorporó o corrigió datos desde esa instantánea, **deténgase y regenere el archivo semanal completo**, conservando todos esos valores. No use estas instantáneas antiguas sobre actividad posterior.
5. Abra **Importar consumos desde CSV o Excel** o **Importar recepciones desde CSV o Excel**, según la pestaña. Revise el archivo antes de seleccionarlo: el botón **Validar e importar consumos/recepciones** valida y escribe inmediatamente, sin una segunda confirmación ni una vista previa separada. Cargue primero consumo y luego recepciones para seguir el recorrido.
6. El cuarto SKU pasará de 184 a 182 existencias al cargar consumo, y luego a 183 existencias / 40 en tránsito al confirmar recepción. Los tres primeros conservan sus saldos preparados.
7. Repetir el mismo archivo para la misma semana conserva el saldo: la API aplica la diferencia frente al total semanal anterior. No cambie la semana para repetir la prueba; hacerlo contabiliza otro período. Una repetición sin diferencia no agrega una entrada de auditoría de movimiento.

**No presione Guardar consumo ni Confirmar recepción con el editor en ceros para una semana ya registrada**: son cantidades semanales de reemplazo, no una indicación de «sin cambios». El historial inferior es de solo lectura.

## Saldos y alcance de la preparación

Se guardaron 3 consumos y 3 recepciones de `2026-W42`, usando `admin` y las APIs existentes. Las cantidades se eligieron pequeñas y dentro de las existencias y el tránsito reales disponibles.

| SKU | Existencias / tránsito antes | Consumo / recepción guardados | Saldo guardado | Consumo / recepción en archivos | Saldo tras ambas cargas |
|---|---|---|---|---|---|
| 11004094 | 30 / 40 | 1 / 2 | 31 / 38 | 1 / 2 | 31 / 38 |
| 11010737 | 111 / 26 | 2 / 1 | 110 / 25 | 2 / 1 | 110 / 25 |
| 11017010 | 24,333333… / 21 | 1 / 2 | 25,333333… / 19 | 1 / 2 | 25,333333… / 19 |
| 11032158 | 184 / 41 | No registrado | 184 / 41 | 2 / 1 | 183 / 40 |

Los otros **433 SKU no cambiaron** durante la preparación. Después de la carga en vivo, serán 432 los SKU sin cambios respecto del respaldo original. `estado_inventario.csv` conserva los 436 saldos anteriores, guardados y esperados tras los archivos. Una recepción conserva la posición de inventario (existencias + tránsito); el consumo la reduce.

| Referencia | Qué contiene |
|---|---|
| `piloto.csv` | Las dos semanas preparadas; referencia para el formulario, no archivo importable en Consumo o Recepciones. |
| `aprobaciones.csv` | Tres aprobaciones guardadas; referencia, no importación. |
| `auditoria.csv` | Instantánea de 10 entradas: 6 movimientos, 3 aprobaciones y 1 reanudación administrativa. |
| `CONTROL_PILOTO.md` | Fórmulas, umbral, pausa, reanudación y límites de interpretación. |

Estas referencias son instantáneas, no se actualizan al operar en la interfaz. Para valores posteriores, consulte la base o descargue nuevamente la auditoría.

## Respaldo y controles observados

- Base: `/app/data/movimientos/operations.sqlite3`, dentro del contenedor de la aplicación.
- Respaldo SQLite consistente, creado **antes de cualquier escritura** mediante `sqlite3.Connection.backup`: `/app/data/movimientos/backups/operations_20261017T043830814201Z.sqlite3`.
- Fecha del respaldo: 17 de octubre de 2026 a las 04:38:30 UTC; la fecha local de la aplicación durante la preparación era 16 de octubre.
- `PRAGMA integrity_check`: `ok` en respaldo y base final.
- Estado previo: 436 filas de inventario, sin movimientos, aprobaciones, métricas piloto ni auditoría; circuito habilitado.
- Estado preparado: 6 movimientos, 3 aprobaciones, 2 métricas piloto y 10 entradas de auditoría. No se sobrescribió ningún registro previo.
- Se verificó el bloqueo de aprobaciones tras dos semanas sobre el umbral. El intento bloqueado no guardó aprobaciones. Administración reanudó y después se guardaron las tres aprobaciones.
- Estado final: `recommendations_paused=false`; aplicación disponible para continuar. Regrabar la segunda semana del piloto vuelve a activar la pausa.

El respaldo está en el volumen operativo del contenedor, no es una copia externa ni un respaldo independiente del volumen. No restaure ni elimine datos durante el recorrido. Una restauración requiere coordinación, respaldo del estado más reciente y una decisión explícita.
