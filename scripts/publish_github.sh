#!/usr/bin/env bash
#
# Publica este repositorio en GitHub, como repositorio publico.
#
#   bash scripts/publish_github.sh                  # usa los valores por defecto
#   USUARIO=otro REPO=otro-nombre bash scripts/publish_github.sh
#   PRIVADO=1 bash scripts/publish_github.sh        # crearlo privado primero
#
# Que hace, en orden:
#   1. comprueba que el arbol esta limpio y que las pruebas pasan
#   2. sustituye tu correo personal por el noreply de GitHub en el historial
#   3. crea el repositorio y sube la rama principal
#   4. deja puesta la descripcion, los temas y la configuracion del repositorio
#
# Es idempotente en lo que puede serlo: si el repositorio ya existe, se salta
# la creacion y solo sube y actualiza los metadatos.

set -euo pipefail

USUARIO="${USUARIO:-Oscarrb1987}"
REPO="${REPO:-aws-data-ingest-pipeline}"
RAMA="${RAMA:-main}"
PRIVADO="${PRIVADO:-0}"

DESCRIPCION="Pipeline serverless en AWS que ingiere CSV, los transforma con Glue y verifica la calidad de los datos dos veces: al cargar y pasada la hora programada."
TEMAS="aws serverless data-engineering step-functions aws-lambda aws-glue amazon-athena aws-cdk data-quality localstack python etl-pipeline infrastructure-as-code"

rojo()  { printf '\033[31m%s\033[0m\n' "$*"; }
verde() { printf '\033[32m%s\033[0m\n' "$*"; }
info()  { printf '\033[36m==>\033[0m %s\n' "$*"; }

abortar() { rojo "ERROR: $*"; exit 1; }

cd "$(dirname "${BASH_SOURCE[0]}")/.."

# ---------------------------------------------------------------- 1. previos

info "Comprobando requisitos"

command -v git >/dev/null || abortar "git no esta instalado."

if ! command -v gh >/dev/null; then
  rojo "La CLI de GitHub (gh) no esta instalada."
  echo
  echo "Instalala:  https://cli.github.com"
  echo "  macOS         brew install gh"
  echo "  Debian/Ubuntu sudo apt install gh"
  echo "  Windows       winget install GitHub.cli"
  echo
  echo "Despues:  gh auth login"
  echo
  echo "Si prefieres no instalarla, sigue los pasos manuales de docs/publicar.md"
  exit 1
fi

gh auth status >/dev/null 2>&1 || abortar "No has iniciado sesion. Ejecuta: gh auth login"

git rev-parse --git-dir >/dev/null 2>&1 || abortar "Esto no es un repositorio git."

if [[ -n "$(git status --porcelain)" ]]; then
  git status --short
  abortar "Hay cambios sin confirmar. Haz commit o guardalos antes de publicar."
fi

# ------------------------------------------------------- 2. correo privado

CUENTA="$(gh api user --jq '.login')"
ID="$(gh api user --jq '.id')"
NOREPLY="${ID}+${CUENTA}@users.noreply.github.com"

# Se compara contra la direccion exacta: la forma corta
# usuario@users.noreply.github.com oculta el correo, pero solo atribuye los
# commits a tu perfil en cuentas anteriores a 2017. La forma id+usuario si.
if git log --format='%ae%n%ce' | sort -u | grep -qxv "${NOREPLY}"; then
  echo
  info "El historial usa correos distintos del noreply de tu cuenta:"
  git log --format='%ae' | sort -u | sed 's/^/  /'
  echo
  echo "Si alguno es personal, en un repositorio publico queda visible para"
  echo "cualquiera y los bots que rastrean commits lo recogen. Y si es un"
  echo "noreply antiguo, GitHub no atribuira los commits a tu perfil."
  echo
  echo "Se reescribiran los $(git rev-list --count HEAD) commits usando:  ${NOREPLY}"
  read -r -p "¿Reescribir el historial? [s/N] " respuesta
  if [[ "${respuesta}" =~ ^[sS]$ ]]; then
    info "Reescribiendo autoria"
    git -c user.name="${CUENTA}" -c user.email="${NOREPLY}" \
        rebase --root --exec 'git commit --amend --no-edit --reset-author' >/dev/null
    git config user.name "${CUENTA}"
    git config user.email "${NOREPLY}"
    verde "Historial reescrito. El correo del repositorio queda fijado a ${NOREPLY}"
  else
    echo "De acuerdo, se mantiene el correo actual."
  fi
fi

# ------------------------------------------------------------ 3. pruebas

info "Ejecutando las pruebas antes de publicar"
if command -v make >/dev/null && make test >/dev/null 2>&1; then
  verde "Pruebas correctas"
else
  rojo "Las pruebas no pasan (o faltan dependencias: make install)."
  read -r -p "¿Publicar de todas formas? [s/N] " seguir
  [[ "${seguir}" =~ ^[sS]$ ]] || exit 1
fi

# ------------------------------------------- 4. crear el repositorio y subir

RUTA="${USUARIO}/${REPO}"

if gh repo view "${RUTA}" >/dev/null 2>&1; then
  info "El repositorio ${RUTA} ya existe; solo se sube y se actualizan los metadatos"
else
  VISIBILIDAD="--public"
  [[ "${PRIVADO}" == "1" ]] && VISIBILIDAD="--private"
  info "Creando ${RUTA} (${VISIBILIDAD#--})"
  gh repo create "${RUTA}" "${VISIBILIDAD}" --description "${DESCRIPCION}" --disable-wiki
fi

git remote get-url origin >/dev/null 2>&1 \
  && git remote set-url origin "https://github.com/${RUTA}.git" \
  || git remote add origin "https://github.com/${RUTA}.git"

git branch -M "${RAMA}"

info "Subiendo la rama ${RAMA}"
git push -u origin "${RAMA}" --force-with-lease

# --------------------------------------------------- 5. metadatos del repo

info "Ajustando descripcion, temas y opciones"

gh repo edit "${RUTA}" \
  --description "${DESCRIPCION}" \
  --enable-issues \
  --enable-discussions \
  --enable-wiki=false \
  --enable-projects=false \
  --delete-branch-on-merge \
  >/dev/null

# shellcheck disable=SC2086
gh repo edit "${RUTA}" $(printf -- '--add-topic %s ' ${TEMAS}) >/dev/null

echo
verde "Listo: https://github.com/${RUTA}"
echo
echo "Siguientes pasos:"
echo "  1. Espera a que la CI termine en verde (pestaña Actions)."
echo "  2. Si lo creaste privado, hazlo publico:"
echo "       gh repo edit ${RUTA} --visibility public --accept-visibility-change-consequences"
echo "  3. Comparte en LinkedIn siguiendo docs/publicar.md"
echo
