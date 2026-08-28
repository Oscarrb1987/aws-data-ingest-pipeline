# Registro de cambios

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/).
Versionado semántico.

## [1.0.0] — 2026-08-28

Primera versión pública.

### Añadido

- Pipeline completo de ingesta y verificación sobre AWS: S3, EventBridge,
  Step Functions, Lambda, Glue, Glue Data Catalog, Athena, DynamoDB, SNS y
  CloudWatch.
- Validación previa a la carga: checksum SHA-256 en streaming, recuento de
  filas y comprobación de cabecera contra el manifest, antes de arrancar Glue.
- Motor de reglas de calidad declarativas en YAML, compiladas a SQL. Seis
  tipos de regla, con severidad crítica o de aviso.
- Doble verificación: una al terminar la carga y otra pasada la hora
  programada, con comparación de huella de partición para detectar reprocesos
  que sobrescriben los datos.
- Ledger de ejecuciones en DynamoDB e informes en S3 en JSON y Markdown.
- Infraestructura como código con AWS CDK en Python, en dos stacks separados
  para que un `cdk destroy` del pipeline no se lleve los datos.
- Proyección de particiones en el catálogo de Glue, en lugar de un crawler.
- Demo local completa con LocalStack y DuckDB, que ejercita los cuatro
  caminos: carga correcta, fichero corrupto, datos sucios y reproceso.
- 89 tests con 96 % de cobertura, sin necesidad de cuenta de AWS.
- Diagrama de arquitectura generado desde código, con verificación en CI de
  que no se queda desfasado.
