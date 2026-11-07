#!/usr/bin/env bash
# Genera eval/muestra/puntos_control.csv (Fase 5) con eval/muestra/generar_muestra.sql.
# Requiere las tablas de las Fases 1 y 2, geo.numero_exterior (./etl/cargar_numeros_exteriores.sh)
# y data/manual/sindicaturas_implan.geojson.
# Uso, desde la raíz del repositorio: ./eval/muestra/generar_muestra.sh
set -euo pipefail
cd "$(dirname "$0")/../.."
# Polígonos de sindicatura digitalizados de los mapas del IMPLAN (etl/digitalizar_sindicaturas.py).
# ST_MakeValid: la vectorización puede dejar anillos que se tocan en un punto.
docker compose run --rm -q gdal ogr2ogr -f PostgreSQL PG:"" /data/manual/sindicaturas_implan.geojson \
  -nln geo.sindicatura_implan -overwrite -a_srs EPSG:6372 -nlt PROMOTE_TO_MULTI -makevalid \
  -lco GEOMETRY_NAME=geom -lco FID=id
docker compose exec -T db sh -c 'psql -q -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  < eval/muestra/generar_muestra.sql > eval/muestra/puntos_control.csv
echo "eval/muestra/puntos_control.csv: $(($(wc -l < eval/muestra/puntos_control.csv) - 1)) puntos"
