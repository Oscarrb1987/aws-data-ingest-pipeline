# Arquitectura

Documento de referencia: qué hace cada pieza, por qué está ahí y qué pasa
cuando algo falla.

## 1. Vista general

```
                       ┌──────────────────────────────────────────────┐
                       │              CUENTA AWS                      │
                       │                                              │
  ┌─────────┐          │  ┌────────────────────────────────────────┐  │
  │ Datamap │──────────┼─►│ S3  datamap-datalake-<env>-<cuenta>    │  │
  │ (origen)│  CSV +   │  │                                        │  │
  └─────────┘  manifest│  │  landing/     dataset=X/dt=YYYY-MM-DD/ │  │
                       │  │  curated/     X/dt=YYYY-MM-DD/*.parquet│  │
                       │  │  quarantine/  ficheros rechazados      │  │
                       │  │  reports/     informes por ejecucion   │  │
                       │  │  config/      contrato de datos        │  │
                       │  └───────────────┬────────────────────────┘  │
                       │                  │ EventBridge               │
                       │                  ▼                           │
                       │  ┌────────────────────────────────────────┐  │
                       │  │ Step Functions: ingest-and-verify      │  │
                       │  └──┬──────┬────────┬────────┬─────────┬──┘  │
                       │     ▼      ▼        ▼        ▼         ▼     │
                       │  Lambda  Glue    Lambda    Wait     Lambda   │
                       │  validar  ETL   verificar  hasta   verificar │
                       │                     A      08:00       B     │
                       │     │      │        │                  │     │
                       │     │      ▼        └────────┬─────────┘     │
                       │     │  Glue Catalog          ▼               │
                       │     │  (proyeccion      Athena workgroup     │
                       │     │   de particiones)                      │
                       │     ▼                                        │
                       │  ┌──────────────┐      ┌──────────────────┐  │
                       │  │ DynamoDB     │      │ SNS  alertas     │──┼──► correo
                       │  │ run ledger   │      └──────────────────┘  │    Slack
                       │  └──────────────┘                            │
                       │  ┌──────────────────────────────────────┐    │
                       │  │ CloudWatch: logs, metricas, alarmas   │   │
                       │  └──────────────────────────────────────┘    │
                       └──────────────────────────────────────────────┘
```

## 2. Máquina de estados

```
   START
     │
     ▼
 ┌───────────────────┐
 │ ValidarFichero    │  Lambda · 1024 MB · 5 min
 │                   │  · manifest presente y bien formado
 │                   │  · el CSV al que apunta existe
 │                   │  · SHA-256 coincide (streaming, sin cargar en memoria)
 │                   │  · nº de filas coincide
 │                   │  · cabecera contiene las columnas obligatorias
 │                   │  · no hay columnas fuera del contrato
 └───┬───────────┬───┘
     │ KO        │ OK
     ▼           │        el fichero se mueve a quarantine/ con su .motivo.txt,
 FicheroRechazado│        el ledger queda QUARANTINED y se envia la alerta
   (Fail)        │
                 ▼
 ┌───────────────────┐
 │ TransformarConGlue│  Glue 4.0 · 2 × G.1X · integracion .sync
 │                   │  · esquema explicito del contrato
 │                   │  · trim y "" -> NULL
 │                   │  · columnas dt, _run_id, _ingested_at
 │                   │  · overwrite dinamico: solo la particion de esa fecha
 └───┬───────────┬───┘
     │ KO        │ OK
     ▼           ▼
 NotificarFallo ┌───────────────────┐
                │ VerificarCargaA   │  Lambda · Athena
                │                   │  · compila rules/checks.yaml a SQL
                │                   │  · ejecuta cada regla
                │                   │  · calcula la huella de la particion
                │                   │  · guarda informe en S3 y huella en el ledger
                └───┬───────────┬───┘
                    │ KO        │ OK  (ledger: LOADED)
                    ▼           ▼
              NotificarFallo  ┌──────────────────────────┐
                              │ CalcularHoraVerificacionB│  Lambda · 256 MB
                              │ 08:00 Europe/Madrid → UTC│
                              └────────────┬─────────────┘
                                           ▼
                              ┌──────────────────────────┐
                              │ EsperarHoraProgramada    │  Wait · timestamp
                              │ (coste cero)             │  absoluto
                              └────────────┬─────────────┘
                                           ▼
                              ┌──────────────────────────┐
                              │ VerificarCargaB          │  mismas reglas
                              │ + comparacion de huella  │  + deteccion de
                              └───┬──────────────────┬───┘    reproceso
                                  │ KO / DRIFT       │ OK
                                  ▼                  ▼
                            NotificarFallo      CargaVerificada
                                  │              (ledger: VERIFIED)
                                  ▼
                                FAIL
```

Tiempo máximo de la máquina: 25 horas, para cubrir el caso de que la
verificación B caiga al día siguiente.

## 3. Estados del ledger

```
  RECEIVED ──► VALIDATED ──► TRANSFORMING ──► LOADED ──► VERIFIED
      │            │                            │           │
      │            ▼                            ▼           ▼
      │       QUARANTINED                     FAILED   DRIFT_DETECTED
      ▼
    FAILED
```

Cada transición escribe `updated_at`. Una ejecución nunca queda "en curso"
para siempre: todos los `Catch` de la máquina desembocan en un estado final.

## 4. Contrato de datos

`rules/checks.yaml` es la única fuente de verdad y alimenta tres consumidores:

```
                    ┌──────────────────────┐
                    │  rules/checks.yaml   │
                    └───┬────────┬─────────┘
                        │        │        │
        ┌───────────────┘        │        └────────────────┐
        ▼                        ▼                         ▼
 ValidarFichero            VerificarCarga            CDK / Glue Catalog
 (columnas                 (reglas → SQL)            (tablas y tipos)
  obligatorias)
```

Un dataset nuevo son unas líneas de YAML: no hay pipeline nuevo, ni tabla
creada a mano, ni riesgo de que el esquema declarado y el catalogado difieran.

### Tipos de regla disponibles

| Tipo | Qué comprueba | SQL generado (resumido) |
| --- | --- | --- |
| `row_count` | filas cargadas == manifest | `COUNT(*)` |
| `not_null` | obligatorios sin nulos ni cadenas vacías | `COUNT(*) WHERE col IS NULL OR col = ''` |
| `unique` | sin duplicados de clave | `SUM(COUNT(*) - 1) GROUP BY pk HAVING COUNT(*) > 1` |
| `accepted_values` | valores dentro del dominio | `COUNT(*) WHERE col NOT IN (…)` |
| `expression` | regla de negocio libre | `COUNT(*) WHERE NOT (expresión)` |
| `business_date_matches_partition` | la fecha del dato cuadra con su partición | `COUNT(*) WHERE fecha <> dt` |

Severidad `critical` detiene el pipeline; `warning` queda en el informe.

## 5. La huella de partición

Tres cifras que resumen el contenido:

```python
Fingerprint(
    row_count       = COUNT(*),
    numeric_checksum= SUM(columnas numéricas),
    distinct_keys   = COUNT(DISTINCT clave),
)
```

Se calcula en la fase A y se recalcula en la B. Cubre los tres tipos de cambio
que una comprobación manual no distingue:

| Qué pasó | row_count | checksum | distinct_keys |
| --- | --- | --- | --- |
| Reproceso que duplica la partición | ✗ cambia | ✗ cambia | = igual |
| Corrección de importes | = igual | ✗ cambia | = igual |
| Llegada tardía de filas nuevas | ✗ cambia | ✗ cambia | ✗ cambia |

El checksum numérico se compara con una tolerancia de 0,01 para absorber el
ruido decimal de la coma flotante.

## 6. Seguridad

- Bucket sin acceso público, cifrado SSE-S3, `enforceSSL`, versionado.
- Un rol IAM por Lambda, con permisos concedidos por CDK a partir del uso real
  (`grant_read_write` sobre el recurso concreto).
- El workgroup de Athena impone su configuración: no se puede escribir el
  resultado fuera del bucket previsto.
- Los nombres de columna que acaban en el SQL se validan (`_ident`): un
  identificador no alfanumérico se rechaza al compilar la regla, no en Athena.
- Sin credenciales en el código ni en el repositorio.

## 7. Ciclo de vida del dato

| Prefijo | Retención | Motivo |
| --- | --- | --- |
| `landing/` | 90 días | ventana de reproceso |
| `quarantine/` | Glacier a los 30 días, borrado al año | es la prueba de por qué un día no se cargó nada |
| `curated/` | indefinida | es el dato |
| `athena-results/` | 14 días | resultados intermedios |
| ledger (DynamoDB) | TTL 2 años | historial de auditoría |

## 8. Qué falta para producción

Cosas conscientemente fuera del alcance de este repositorio:

- **Backfill**: reejecutar un rango de fechas. El job ya es idempotente por
  partición, falta el orquestador que itere sobre el rango.
- **Esquemas evolutivos**: hoy una columna nueva en el origen rompe la
  validación. Lo correcto sería versionar el contrato.
- **Cuarentena parcial**: ahora se rechaza el fichero entero; separar las filas
  malas y cargar el resto es otra decisión de negocio.
- **Panel**: el ledger tiene todo lo necesario para un QuickSight o un Grafana.
