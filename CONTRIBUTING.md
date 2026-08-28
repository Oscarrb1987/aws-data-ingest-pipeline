# Cómo contribuir

Gracias por pasarte por aquí. Este proyecto es pequeño y con opiniones claras,
así que antes de invertir tu tiempo merece la pena leer esto.

## Antes de escribir código

Abre un issue si vas a proponer un cambio que no sea una corrección obvia.
Una conversación de cinco minutos ahorra una tarde de trabajo descartado.

Encajan especialmente bien:

- tipos de regla nuevos en el motor de calidad (`src/common/rules.py`)
- soporte para más formatos de origen además de CSV
- un backfill que reejecute un rango de fechas
- mejoras en la demo local

Encajan mal, salvo que expliques muy bien por qué:

- añadir dependencias pesadas a las Lambdas (el paquete son 2,8 MB y así se queda)
- lógica de negocio que debería ser configuración en `rules/checks.yaml`
- acoplar el código de verificación a Athena (el punto de `QueryEngine` es
  precisamente que no dependa de un motor concreto)

## Entorno de desarrollo

```bash
make install     # dependencias, incluido el extra [dev]
make up          # LocalStack + recursos de la demo
make demo        # pipeline completo de principio a fin
```

## Antes de abrir el pull request

```bash
make lint        # ruff check + ruff format --check
make test        # pytest, sin necesidad de cuenta de AWS
make diagram     # solo si tocaste la arquitectura
make synth       # solo si tocaste infra/
```

La CI ejecuta lo mismo, más la demo completa contra LocalStack. Si `make test`
pasa en tu máquina, la CI debería pasar también.

## Qué esperamos de un pull request

**Un test que falle antes de tu cambio y pase después.** Las pruebas usan moto
y DuckDB, así que corren en segundos y no necesitan credenciales. No hay excusa.

**Cobertura por encima del 85 %.** La CI lo comprueba y falla por debajo.

**Comentarios que expliquen el porqué, no el qué.** El código ya dice lo que
hace. Los comentarios están para lo que no se ve: por qué se sondea en vez de
esperar, por qué el disparador escucha al manifest y no al CSV.

**Mensajes de commit que expliquen el problema**, no solo la solución. "Arreglar
el cálculo del checksum en ficheros sin salto de línea final" es útil; "fix bug"
no lo es.

## Estilo

`ruff` decide, tú no discutes. Línea de 100 caracteres. El código y los
comentarios están en español sin tildes en los identificadores; los nombres
técnicos de AWS se dejan en inglés.

## Licencia

Al contribuir aceptas que tu aportación se publique bajo la licencia MIT del
repositorio.
