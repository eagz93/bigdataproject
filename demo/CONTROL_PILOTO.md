# Cómo interpretar y operar el control piloto

El control compara tasas semanales de quiebre entre piloto y control. **Pausa las aprobaciones cuando el piloto supera relativamente al control en más del 15% durante dos semanas ISO consecutivas.** No demuestra por sí solo que el modelo mejore o empeore el negocio. Las dos semanas guardadas en esta entrega son valores preparados para mostrar el mecanismo, no mediciones históricas verificadas.

## Cálculo y ejemplo guardado

Para cada grupo, una exposición es una oportunidad de observar un quiebre según la definición operativa acordada; no se deduce automáticamente de los movimientos de inventario.

```text
tasa_piloto  = quiebres_piloto / exposiciones_piloto
tasa_control = quiebres_control / exposiciones_control
exceso_relativo = (tasa_piloto / tasa_control) - 1     si tasa_control > 0
semana_sobre_limite = tasa_piloto > tasa_control × 1,15
```

| Semana ISO | Fechas (lunes–domingo) | Piloto | Control | Exceso relativo | Sobre el límite |
|---|---|---|---|---|---|
| 2026-W40 | 28 septiembre–4 octubre 2026 | 12 / 100 = 12% | 10 / 100 = 10% | 20% | Sí |
| 2026-W41 | 5–11 octubre 2026 | 13 / 100 = 13% | 10 / 100 = 10% | 30% | Sí |

En la primera semana hay una diferencia de **2 puntos porcentuales**, pero un aumento **relativo de 20%**. La regla no exige 15 puntos porcentuales. El operador es estrictamente `>`: matemáticamente, un exceso de exactamente 15% no supera el límite.

La decisión usa multiplicación cruzada de los conteos enteros y el umbral racional exacto, sin comparar tasas redondeadas ni productos de punto flotante. Se verificó que control `20/100` y piloto `23/100` (o `46/200`) **no** superan el límite: representan exactamente 15% de aumento relativo. Con piloto `45/200` queda por debajo y con `47/200` queda por encima. Las tasas almacenadas siguen siendo fracciones de punto flotante para visualización; no determinan la decisión de umbral.

Las tasas guardadas se muestran como fracciones: `0.12` significa 12%. El campo `above_limit=1` indica una semana por encima del umbral; no equivale por sí solo a un circuito actualmente pausado.

## Reglas de validación y casos límite

- Quiebres y exposiciones deben ser enteros no negativos. Cada exposición debe ser mayor que cero; los quiebres no pueden superar las exposiciones.
- Cuando control tiene cero quiebres, cualquier tasa piloto positiva se considera por encima del límite. Si ambos tienen cero quiebres, la semana no está por encima. El aumento relativo porcentual no está definido cuando el denominador control es cero.
- Deben ser semanas ISO **consecutivas del calendario**, incluso al pasar de año. Dos filas consecutivas de una tabla con semanas intermedias ausentes no bastan.
- El disparo se evalúa al guardar una semana frente a su semana inmediatamente anterior. Para reproducirlo, guarde primero la más antigua y luego la siguiente; no suponga que una carga fuera de orden recalcula todo el historial.
- Una semana que no supera el límite rompe la pareja para la siguiente evaluación. Una pausa ya activa permanece hasta una reanudación administrativa; corregir cifras o registrar una semana favorable no reanuda automáticamente.
- Guardar la misma semana reemplaza sus métricas. No sobrescriba mediciones operativas para repetir una presentación. En esta preparación las semanas elegidas estaban libres.

## Operación en la interfaz

1. Revise el historial de **Control piloto** y su estado actual. `piloto.csv` es una referencia de lectura, no existe un importador CSV de métricas piloto.
2. Con CEDI o Administración, complete semana, exposiciones y quiebres de ambos grupos y guarde.
3. Si se activa el circuito, **Plan y aprobación** bloquea nuevas aprobaciones tanto en la interfaz como en la API. Las aprobaciones existentes permanecen guardadas.
4. Investigue cobertura, definición de exposición, calidad de datos y causas operativas antes de decidir continuar.
5. Solo Administración puede pulsar **Reanudar tras revisión**. Es una acción manual auditada como `reanudar_circuito`. No borra ni modifica las métricas.

La pausa afecta a las **aprobaciones**, no detiene el scheduler, el ETL, el cálculo o visualización del plan, ni las capturas de consumo, recepción o métricas. No existe un freno de ejecución logística externo ni una aprobación automática.

### Estado dejado en esta entrega

Se guardaron W40 y W41 en orden, se verificó que W41 activara la pausa y que un intento de aprobación fuera rechazado sin persistir órdenes. Después `admin` reanudó y guardó tres aprobaciones de W42. El estado final es **habilitado** (`recommendations_paused=false`).

Las métricas siguen sobre el umbral en el historial, aunque el circuito esté habilitado por decisión administrativa. Si vuelve a guardar W41 con esos valores, se activará nuevamente: reanude manualmente al terminar el recorrido autorizado. No necesita regrabar nada para mostrar el historial.

## Trazabilidad y límites de evidencia

Los movimientos y aprobaciones usan la auditoría ordinaria, sin etiquetas especiales por elección del usuario. Las métricas conservan `entered_by` y `entered_at`, pero la API actual **no genera una entrada de auditoría para cada cambio de métrica ni para el disparo** y no conserva versiones anteriores de una misma semana. La reanudación sí queda en la auditoría; un intento de aprobación bloqueado no genera un registro de auditoría independiente.

Por eso, el historial y `piloto.csv` muestran los valores guardados, pero no son una bitácora completa de todas sus revisiones. Para una evaluación de negocio, recopile evidencia original verificable, una definición estable de exposición, grupos comparables y suficiente seguimiento. No atribuya causalidad ni afirme reducción de quiebres a partir de estas cifras preparadas.

Vea [la guía de demostración](GUIA_DEMOSTRACION.md) para los saldos exactos, las instantáneas semanales de importación y la ruta del respaldo anterior a las escrituras.
