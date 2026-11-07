#!/usr/bin/env bash
# Genera eval/muestra/puntos_control.csv (Fase 5) con eval/muestra/generar_muestra.sql.
# Requiere las tablas de las Fases 1 y 2 y geo.numero_exterior (./etl/cargar_numeros_exteriores.sh).
# Uso, desde la raíz del repositorio: ./eval/muestra/generar_muestra.sh
set -euo pipefail
cd "$(dirname "$0")/../.."
docker compose exec -T db sh -c 'psql -q -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  < eval/muestra/generar_muestra.sql > eval/muestra/puntos_control.csv
echo "eval/muestra/puntos_control.csv: $(($(wc -l < eval/muestra/puntos_control.csv) - 1)) puntos"
