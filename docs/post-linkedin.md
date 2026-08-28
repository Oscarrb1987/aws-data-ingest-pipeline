# Post para LinkedIn

Sustituye `Oscarrb1987` por tu usuario de GitHub antes de publicar.

---

## Versión principal

Cada mañana hacía lo mismo: subir un CSV, lanzar el job que lo carga, mirar si
los datos estaban, y volver a mirar después de la hora programada.

Cuatro pasos, veinte minutos, y un punto ciego que tardé en ver.

Contar filas dos veces no detecta que alguien haya reprocesado la partición por
el medio. Si el proceso la borra y la vuelve a escribir con otro contenido, el
conteo puede cuadrar igual. El dato está mal y la comprobación dice que está
bien.

Así que lo he montado entero en AWS, y he resuelto ese punto ciego:

→ EventBridge dispara todo cuando llega el manifest a S3. Ya nadie tiene que
acordarse.

→ Una Lambda valida checksum y número de filas ANTES de arrancar Glue. Si el
fichero viene corrupto, va a cuarentena y el clúster no llega a levantarse.

→ Glue transforma a Parquet particionado. Step Functions espera con un estado
Wait hasta la hora acordada: esperar seis horas cuesta cero.

→ Y aquí lo importante: la primera verificación guarda una huella de la
partición (filas + suma de importes + claves distintas). La segunda la
recalcula y las compara. Un reproceso que pisa datos ya no pasa desapercibido.

Las reglas de calidad viven en un YAML que se compila a SQL. Añadir una
comprobación es un pull request, no un despliegue.

Lo que más me ha costado: aceptar que la parte difícil no era la arquitectura,
sino escribir qué significa exactamente "los datos están bien".

Repo con la infraestructura en CDK, tests y una demo que corre en local sin
cuenta de AWS 👇
github.com/Oscarrb1987/aws-data-ingest-pipeline

#AWS #DataEngineering #Serverless #StepFunctions #CDK #DataQuality

---

## Versión corta (si prefieres algo más ligero)

Automaticé la tarea que hacía todas las mañanas: subir un CSV, lanzar la carga
y comprobar dos veces que los datos estaban bien.

Lo interesante no fue automatizar los pasos. Fue darme cuenta de que la
comprobación manual tenía un agujero: contar filas dos veces no detecta que
alguien haya reprocesado la partición por el medio.

La solución fue guardar una huella de los datos en la primera verificación
(filas + suma de importes + claves distintas) y compararla en la segunda.

Todo serverless: S3 + EventBridge + Step Functions + Lambda + Glue + Athena,
desplegado con CDK. Las reglas de calidad son YAML que se compila a SQL.

Menos de un euro al mes. Y funciona en local sin cuenta de AWS.

github.com/Oscarrb1987/aws-data-ingest-pipeline

#AWS #DataEngineering #Serverless #DataQuality

---

## Notas para publicar

- **Imagen**: el diagrama ASCII del README no se lee bien en móvil. Mejor una
  captura de la máquina de estados de Step Functions (la consola de AWS la
  dibuja bien) o del resumen del ledger cuando detecta la divergencia.
- **Primer comentario**: pon ahí el enlace al repo si notas que LinkedIn
  penaliza los enlaces en el cuerpo del post.
- **Momento**: martes o miércoles por la mañana suele funcionar mejor para
  contenido técnico.
- **Si te preguntan por el coste**: la tabla del README tiene el desglose.
