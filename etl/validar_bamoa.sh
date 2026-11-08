#!/usr/bin/env bash
# Fase 2, paso 5: compara el polígono de Bamoa digitalizado del mapa del IMPLAN
# (la entidad Bamoa de data/manual/sindicaturas_implan.geojson) con el polígono
# de Voronoi de Bamoa.
# Reporta intersección / área IMPLAN, intersección / área Voronoi e
# intersección / unión (IoU).
# El GeoJSON lo genera etl/digitalizar_sindicaturas.py. Uso, desde la raíz y después de ./etl/cargar_sindicaturas.sh:
#   ./etl/validar_bamoa.sh
set -euo pipefail
cd "$(dirname "$0")/.."

ARCHIVO=data/manual/sindicaturas_implan.geojson
if [ ! -f "$ARCHIVO" ]; then
  echo "Falta $ARCHIVO (se genera con etl/digitalizar_sindicaturas.py; ver CLAUDE.md)." >&2
  exit 1
fi

# El GeoJSON se reproyecta a EPSG:6372 desde el SRS que declare (4326 por omisión).
docker compose run --rm -q gdal ogr2ogr -f PostgreSQL PG:"" "/$ARCHIVO" \
  -where "sindicatura = 'Bamoa'" -nln geo.bamoa_implan -overwrite -t_srs EPSG:6372 -nlt PROMOTE_TO_MULTI \
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

-- Sensibilidad a la georreferencia: IoU con el polígono del IMPLAN desplazado
-- una distancia igual al RMS de su georreferencia (rms_m) en 8 direcciones.
WITH i AS (SELECT ST_Union(ST_MakeValid(geom)) AS geom, max(rms_m[1]) AS rms FROM geo.bamoa_implan),
     v AS (SELECT geom FROM geo.sindicatura_poligono WHERE sindicatura = 'Bamoa'),
     d AS (SELECT ST_Translate(i.geom, i.rms * cos(radians(t)), i.rms * sin(radians(t))) AS geom, i.rms
           FROM i, generate_series(0, 315, 45) t),
     u AS (SELECT d.rms, ST_Area(ST_Intersection(d.geom, v.geom)) / ST_Area(ST_Union(d.geom, v.geom)) AS iou FROM d, v)
SELECT rms AS desplazamiento_m, round(min(iou)::numeric, 4) AS iou_min, round(max(iou)::numeric, 4) AS iou_max
FROM u GROUP BY rms;
SQL
