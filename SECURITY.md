# Política de seguridad

## Cómo reportar una vulnerabilidad

**No abras un issue público.** Usa la pestaña *Security* del repositorio →
*Report a vulnerability*, que abre un aviso privado que solo ve quien mantiene
el proyecto.

Responderé en un plazo razonable. Si el fallo es real, publicaré el arreglo y
te acreditaré, salvo que prefieras lo contrario.

## Alcance

Este repositorio es una implementación de referencia. Interesan sobre todo:

- inyección de SQL a través de `rules/checks.yaml` (las reglas se compilan a
  SQL; los identificadores se validan en `src/common/rules.py::_ident`, pero
  el campo `expression` es deliberadamente libre)
- permisos IAM más amplios de lo necesario en `infra/stacks/`
- fuga de datos en logs o en los informes que se escriben en S3

## Antes de desplegarlo en tu cuenta

Este código despliega infraestructura real y cuesta dinero real. Repasa al
menos esto:

- **`rules/checks.yaml` es código con privilegios.** El campo `expression` se
  interpola directamente en el SQL que ejecuta Athena. Quien pueda editar ese
  fichero puede ejecutar SQL arbitrario contra tu catálogo. Trátalo como
  código: revisión obligatoria en el pull request.
- **El bucket es privado y con `enforceSSL`.** No lo abras "solo para probar".
- **El límite de bytes escaneados del workgroup de Athena** está en 1 GB por
  consulta. Es un tope de coste, no de seguridad, pero quítalo y una consulta
  mal escrita puede salir cara.
- **Los informes en `reports/` contienen recuentos, no filas de datos.** Si
  añades reglas que devuelvan ejemplos de filas que fallan, revisa que no
  acabes escribiendo datos personales en un prefijo con otra política de
  acceso.
- **El ledger de DynamoDB guarda nombres de fichero y recuentos.** Si tus
  nombres de fichero llevan información sensible, tenlo en cuenta.

## Lo que este proyecto no hace

No cifra con KMS gestionado por el cliente, no aísla en VPC, no implementa
control de acceso por columna ni enmascarado. Si lo necesitas, es trabajo tuyo
antes de llevarlo a producción.
