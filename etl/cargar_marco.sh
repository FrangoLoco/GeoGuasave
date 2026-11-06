#!/usr/bin/env bash
# Carga las siete capas del Marco Geoestadístico 2022 de Sinaloa al esquema geo.
# Idempotente: cada corrida reemplaza las tablas (ogr2ogr -overwrite) y repite
# la validación, los índices y ANALYZE.
# Uso, desde la raíz del repositorio: ./etl/cargar_marco.sh
set -euo pipefail
cd "$(dirname "$0")/.."

ZIP=data/raw/25_sinaloa.zip
SHA256=57d4242eebb9366e70a6f34ee8e0f2e39eaeb686e1da9e8849353ceb4aa99674
echo "$SHA256  $ZIP" | sha256sum -c -

# capa INEGI -> tabla en geo
declare -A TABLA=(
  [mun]=municipio
  [l]=localidad
  [pe]=poligono_externo
  [pem]=poligono_externo_manzana
  [lpr]=localidad_puntual
  [a]=ageb_urbana
  [ar]=ageb_rural
)

for capa in mun l pe pem lpr a ar; do
  tipo=PROMOTE_TO_MULTI
  [ "$capa" = lpr ] && tipo=POINT
  echo "Cargando 25$capa -> geo.${TABLA[$capa]}"
  # La codificación la toma GDAL del .cpg de cada capa (UTF-8 o ISO 8859-1).
  # -a_srs: el .prj es EPSG:6372 (verificado con gdalsrsinfo -e); solo se asigna la clave, no se reproyecta.
  docker compose run --rm -q gdal ogr2ogr -f PostgreSQL PG:"" \
    "/vsizip//data/raw/25_sinaloa.zip/25_sinaloa/conjunto_de_datos/25$capa.shp" \
    -nln "geo.${TABLA[$capa]}" -overwrite \
    -a_srs EPSG:6372 -nlt "$tipo" \
    -lco GEOMETRY_NAME=geom -lco FID=id -lco SPATIAL_INDEX=NONE
done

docker compose exec -T db sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < etl/post_carga.sql
