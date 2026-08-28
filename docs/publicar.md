# Publicar en GitHub y compartir en LinkedIn

Guía de una sola pasada. Al final tienes el repositorio público, la CI en
verde y el post publicado.

---

## Parte 1 · Subirlo a GitHub

### Camino rápido (recomendado)

Necesitas la [CLI de GitHub](https://cli.github.com) instalada y con sesión
iniciada:

```bash
gh auth login          # solo la primera vez
bash scripts/publish_github.sh
```

El script hace todo lo que viene después en este documento: comprueba que el
árbol está limpio, ejecuta las pruebas, te ofrece quitar tu correo personal del
historial, crea el repositorio público, sube la rama y deja puestas la
descripción y las etiquetas.

Si prefieres verlo primero en privado y publicarlo cuando la CI esté en verde:

```bash
PRIVADO=1 bash scripts/publish_github.sh
# ...cuando estés conforme:
gh repo edit Oscarrb1987/aws-data-ingest-pipeline \
  --visibility public --accept-visibility-change-consequences
```

### Camino manual

Si no quieres instalar nada:

**1. Quita tu correo personal del historial.** En un repositorio público, el
correo de cada commit queda visible para cualquiera y los bots lo recogen.
Copia tu dirección exacta desde GitHub → *Settings* → *Emails* → *Keep my email
addresses private*; tiene la forma `12345678+usuario@users.noreply.github.com`.

```bash
git config user.name  "Oscarrb1987"
git config user.email "TU-ID+Oscarrb1987@users.noreply.github.com"
git rebase --root --exec 'git commit --amend --no-edit --reset-author'
```

**2. Crea el repositorio** en <https://github.com/new>:

- Nombre: `aws-data-ingest-pipeline`
- Visibilidad: **Public**
- **No** marques ninguna casilla de inicialización (README, .gitignore,
  licencia): el repositorio local ya los trae y chocarían.

**3. Súbelo:**

```bash
git remote add origin https://github.com/Oscarrb1987/aws-data-ingest-pipeline.git
git branch -M main
git push -u origin main
```

**4. Ajusta la ficha del repositorio.** En la portada, el engranaje junto a
*About*:

- **Descripción**: Pipeline serverless en AWS que ingiere CSV, los transforma
  con Glue y verifica la calidad de los datos dos veces: al cargar y pasada la
  hora programada.
- **Temas**: `aws` `serverless` `data-engineering` `step-functions`
  `aws-lambda` `aws-glue` `amazon-athena` `aws-cdk` `data-quality`
  `localstack` `python` `etl-pipeline` `infrastructure-as-code`
- Desmarca *Wikis* y *Projects*. Deja *Issues* y activa *Discussions*.

### Después de subirlo

- **Comprueba la pestaña Actions.** Los cuatro trabajos deben quedar en verde.
  Un repositorio de portafolio con la CI en rojo resta en lugar de sumar.
- **Protege `main`** (*Settings* → *Branches* → *Add rule*): exige que la CI
  pase antes de fusionar. Con un repositorio de una sola persona parece
  excesivo, pero es exactamente lo que mira quien te evalúa.
- **Fija el repositorio en tu perfil** (*Customize your pins*). Es lo primero
  que ve quien llega desde LinkedIn.

---

## Parte 2 · Compartirlo en LinkedIn

### Antes de publicar

- [ ] La CI está en verde
- [ ] El README se ve bien en móvil (ábrelo desde el teléfono; el diagrama
      debe cargar y las tablas no deben desbordar)
- [ ] El repositorio está fijado en tu perfil
- [ ] Tu titular de LinkedIn dice algo coherente con el post

### Qué publicar

El texto está en [`post-linkedin.md`](post-linkedin.md), con dos versiones.
La principal cuenta el punto ciego del proceso manual; la corta va al grano.

Las URL ya apuntan a `Oscarrb1987/aws-data-ingest-pipeline`; si publicas con
otro nombre, ajústalas.

### Cómo publicarlo

**1. La imagen.** LinkedIn muestra una imagen grande y un enlace pequeño, así
que la imagen hace casi todo el trabajo. Opciones, de mejor a peor:

- El diagrama en oscuro (`docs/aws-architecture-dark.svg`) exportado a PNG.
  LinkedIn no acepta SVG. Ábrelo en el navegador y haz una captura, o:
  ```bash
  # si tienes rsvg-convert o Inkscape a mano
  rsvg-convert -w 2400 docs/aws-architecture-dark.svg -o diagrama.png
  ```
- Una captura de la máquina de estados en la consola de AWS, si llegas a
  desplegarlo. Tiene más credibilidad que cualquier diagrama.
- Una captura del resumen del ledger cuando detecta la divergencia. Es la
  parte interesante del proyecto y cabe en una pantalla.

Formato: 1200 × 627 px o cuadrada. Si el texto no se lee en el móvil, recorta
en vez de reducir.

**2. El enlace.** LinkedIn penaliza los enlaces salientes en el cuerpo del
post. Pon el enlace en el **primer comentario**, nada más publicar, y en el
cuerpo escribe algo como "enlace al repo en comentarios".

**3. El momento.** Martes o miércoles entre las 8:00 y las 10:00 suele
funcionar para contenido técnico en España. Evita viernes por la tarde.

**4. La primera hora manda.** El alcance se decide en los primeros 60 minutos.
Quédate cerca para responder comentarios; cada respuesta empuja el post.

### Cuando lleguen las preguntas

Ten a mano de dónde sale cada respuesta:

| Te preguntarán | Está en |
| --- | --- |
| ¿Cuánto cuesta? | Tabla de costes del README |
| ¿Por qué no Airflow / MWAA? | Ver abajo |
| ¿Por qué no Databricks? | Ver abajo |
| ¿Y si el fichero pesa 10 GB? | Checksum y conteo en streaming; Glue escala con `--enable-auto-scaling` |
| ¿Cómo pruebo esto sin cuenta de AWS? | `make up && make demo` |
| ¿Se puede hacer backfill? | Todavía no: está en "Qué falta para producción" |

**Sobre Airflow:** un pipeline de un dataset diario no justifica mantener un
scheduler encendido. Step Functions cuesta céntimos y no hay nada que
parchear. Con veinte pipelines con dependencias entre ellos, la respuesta
cambiaría.

**Sobre Databricks:** el proceso original usaba Databricks. Se puede
reimplementar cambiando el estado de Glue por una llamada a la Jobs API 2.1
con el token en Secrets Manager; el resto del pipeline no se entera. Se eligió
Glue para que cualquiera pueda desplegarlo sin una suscripción de por medio.

### Lo que no conviene hacer

- **No cuentes cifras internas de tu empresa** (volúmenes reales, nombres de
  sistemas, incidencias concretas). El repo ya está neutralizado; el post
  también debería estarlo.
- **No prometas mantenimiento** que no vayas a dar. "Es una implementación de
  referencia" es una respuesta perfectamente digna.
- **No pongas veinte hashtags.** Tres o cuatro relevantes rinden más.

### Una semana después

Mira el tráfico del repositorio en *Insights* → *Traffic*. Si hubo visitas
pero ninguna estrella, casi siempre es el README: o no se entiende en los
primeros diez segundos qué hace, o no queda claro cómo probarlo.
