#!/usr/bin/env bash
# Corre las pruebas de geo.reverse_geocode contra la base (Fase 3).
# Primero carga db/sql/reverse_geocode.sql, para probar siempre la versión del repositorio.
# Uso, desde la raíz del repositorio: ./tests/correr.sh
set -euo pipefail
cd "$(dirname "$0")/.."

psql() {
  docker compose exec -T db sh -c 'psql -q -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
}

psql < db/sql/reverse_geocode.sql
psql < tests/test_reverse_geocode.sql

# 8. EXPLAIN ANALYZE de una consulta típica (un punto en la ciudad de Guasave):
#    auto_explain muestra los planes de las consultas internas de la función.
planes=$(psql 2>&1 <<'SQL'
LOAD 'auto_explain';
SET auto_explain.log_min_duration = 0;
SET auto_explain.log_analyze = on;
SET auto_explain.log_nested_statements = on;
SET auto_explain.log_level = notice;
SET client_min_messages = notice;
SELECT geo.reverse_geocode(-108.4697, 25.5674) \g /dev/null
SQL
)
echo "8. Índices GiST usados en una consulta típica:"
usados=$(grep -o '[a-z_]*_geom_gist' <<<"$planes" | sort | uniq -c)
echo "$usados"
if ! grep -q localidad_geom_gist <<<"$usados" || ! grep -q municipio_geom_gist <<<"$usados"; then
  echo "8. FALLA: no se usan los índices GiST esperados" >&2
  echo "$planes" >&2
  exit 1
fi
if grep -q 'Seq Scan on \(localidad\|municipio\|ageb_urbana\|ageb_rural\|poligono_externo\|localidad_puntual\|sindicatura_poligono\)' <<<"$planes"; then
  echo "8. FALLA: hay barridos secuenciales sobre capas geográficas" >&2
  grep -B2 -A2 'Seq Scan' <<<"$planes" >&2
  exit 1
fi
echo "8. ok"
