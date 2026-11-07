#!/usr/bin/env bash
# Levanta GeoGuasave desde cero con los datos cargados (Fase 4, tarea 3):
# base de datos, Marco Geoestadístico 2022, sindicaturas (IMPLAN + Voronoi),
# función geo.reverse_geocode y la API. Idempotente: cada corrida recarga los
# datos desde data/raw/25_sinaloa.zip y los CSV de data/manual/.
# Uso, desde la raíz del repositorio: ./iniciar.sh
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f .env ]; then
  echo "Falta .env: cp .env.example .env y cambia POSTGRES_PASSWORD." >&2
  exit 1
fi
if [ ! -f data/raw/25_sinaloa.zip ]; then
  echo "Falta data/raw/25_sinaloa.zip (INEGI, Marco Geoestadístico 2022, UPC 889463770541)." >&2
  exit 1
fi

echo "1/5 Base de datos"
docker compose up -d --wait db
echo "2/5 Marco Geoestadístico 2022"
./etl/cargar_marco.sh
echo "3/5 Sindicaturas"
./etl/cargar_sindicaturas.sh
echo "4/5 Función geo.reverse_geocode"
docker compose exec -T db sh -c 'psql -q -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < db/sql/reverse_geocode.sql
echo "5/5 API"
docker compose up -d --build --wait api

set -a; . ./.env; set +a
echo "GeoGuasave listo en http://127.0.0.1:${API_PORT:-8000} (documentación en /docs)"
