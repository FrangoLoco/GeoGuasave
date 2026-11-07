#!/usr/bin/env bash
# Carga los números exteriores (capa ne) de las localidades amanzanadas de Guasave
# en geo.numero_exterior (Fase 5). Fuente: INEGI, Información vectorial de
# localidades amanzanadas y números exteriores 2023 (UPC 794551086223), una
# carpeta por localidad. Idempotente: la tabla se recrea en cada corrida.
# Uso, desde la raíz del repositorio: ./etl/cargar_numeros_exteriores.sh
set -euo pipefail
cd "$(dirname "$0")/.."

ZIP=data/raw/794551086223_ss.zip
SHA256=acdf3995184e7351ef78cfd720c0047db12e513b662455ab6b6567962b638ab0
echo "$SHA256  $ZIP" | sha256sum -c -

# Carpetas de localidad (clave de 9 dígitos) dentro del zip.
claves=$(python3 -I -c "
import sys, zipfile
print(' '.join(sorted({n.split('/')[0] for n in zipfile.ZipFile(sys.argv[1]).namelist() if n[:9].isdigit()})))" "$ZIP")
echo "Localidades en el zip: $(wc -w <<<"$claves")"

# Un solo contenedor; la primera capa crea la tabla y las demás se agregan.
# -a_srs: el .prj es EPSG:6372 (verificado con gdalsrsinfo -e).
docker compose run --rm -q gdal sh -c '
  set -e; modo="-overwrite -lco GEOMETRY_NAME=geom -lco FID=id -lco SPATIAL_INDEX=NONE"
  for c in '"$claves"'; do
    ogr2ogr -f PostgreSQL PG:"" "/vsizip//data/raw/794551086223_ss.zip/$c/conjunto_de_datos/${c}ne.shp" \
      -nln geo.numero_exterior $modo -a_srs EPSG:6372 -nlt POINT
    modo="-append"
  done'

docker compose exec -T db sh -c 'psql -q -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' <<'SQL'
CREATE INDEX numero_exterior_geom_gist ON geo.numero_exterior USING gist (geom);
CREATE INDEX numero_exterior_cvegeo ON geo.numero_exterior (cvegeo);
ANALYZE geo.numero_exterior;
SQL
