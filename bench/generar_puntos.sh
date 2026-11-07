#!/usr/bin/env bash
# Genera bench/puntos.json: 1,000 coordenadas al azar dentro de Guasave (EPSG:4326),
# con la semilla del proyecto (2026). Las usa el script de k6 de la prueba preliminar.
# Uso, desde la raíz del repositorio: ./bench/generar_puntos.sh
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose exec -T db sh -c 'psql -qAt -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' > bench/puntos.json <<'SQL'
SELECT json_agg(json_build_array(round(ST_Y(g)::numeric, 6), round(ST_X(g)::numeric, 6)) ORDER BY i)
FROM (SELECT d.path[1] AS i, ST_Transform(d.geom, 4326) AS g
      FROM geo.municipio m, ST_Dump(ST_GeneratePoints(m.geom, 1000, 2026)) d
      WHERE m.cvegeo = '25011') p;
SQL
echo "bench/puntos.json: $(grep -o '\], \[' bench/puntos.json | wc -l | awk '{print $1+1}') puntos [lat, lon]"
