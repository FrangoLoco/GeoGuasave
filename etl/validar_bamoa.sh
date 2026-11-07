#!/usr/bin/env bash
# Fase 2, paso 5: compara el polígono de Bamoa digitalizado del mapa del IMPLAN
# (data/manual/bamoa_implan.geojson) con el polígono de Voronoi de Bamoa.
# Reporta intersección / área IMPLAN, intersección / área Voronoi e
# intersección / unión (IoU).
# Uso, desde la raíz del repositorio y después de ./etl/cargar_sindicaturas.sh:
#   ./etl/validar_bamoa.sh
set -euo pipefail
cd "$(dirname "$0")/.."

ARCHIVO=data/manual/bamoa_implan.geojson
if [ ! -f "$ARCHIVO" ]; then
  echo "Falta $ARCHIVO (se digitaliza en QGIS a partir del mapa del IMPLAN)." >&2
  exit 1
fi

# El GeoJSON se reproyecta a EPSG:6372 desde el SRS que declare (4326 por omisión).
docker compose run --rm -q gdal ogr2ogr -f PostgreSQL PG:"" "/data/manual/bamoa_implan.geojson" \
  -nln geo.bamoa_implan -overwrite -t_srs EPSG:6372 -nlt PROMOTE_TO_MULTI \
  -lco GEOMETRY_NAME=geom -lco FID=id

docker compose exec -T db sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' <<'SQL'
WITH i AS (SELECT ST_Union(ST_MakeValid(geom)) AS geom FROM geo.bamoa_implan),
     v AS (SELECT geom FROM geo.sindicatura_poligono WHERE sindicatura = 'Bamoa'),
     a AS (SELECT ST_Area(i.geom) AS implan, ST_Area(v.geom) AS voronoi,
                  ST_Area(ST_Intersection(i.geom, v.geom)) AS inter,
                  ST_Area(ST_Union(i.geom, v.geom)) AS union_ FROM i, v)
SELECT round((implan / 1e6)::numeric, 2) AS implan_km2,
       round((voronoi / 1e6)::numeric, 2) AS voronoi_km2,
       round((inter / 1e6)::numeric, 2) AS interseccion_km2,
       round((inter / implan)::numeric, 4) AS inter_sobre_implan,
       round((inter / voronoi)::numeric, 4) AS inter_sobre_voronoi,
       round((inter / union_)::numeric, 4) AS iou
FROM a;
SQL
