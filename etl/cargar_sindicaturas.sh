#!/usr/bin/env bash
# Fase 2, pasos 3 y 4: carga data/manual/localidad_sindicatura.csv y genera
# geo.localidad_sindicatura y geo.sindicatura_poligono (db/sql/sindicaturas.sql).
# Idempotente: cada corrida reemplaza las dos tablas, en una sola transacción.
# Uso, desde la raíz del repositorio: ./etl/cargar_sindicaturas.sh
set -euo pipefail
cd "$(dirname "$0")/.."

{
  echo 'BEGIN;'
  echo 'CREATE TEMP TABLE implan (cvegeo varchar(9) PRIMARY KEY, nombre_inegi text, nombre_implan text,'
  echo '  unidad text NOT NULL, metodo_match text NOT NULL, puntaje numeric) ON COMMIT DROP;'
  echo 'COPY implan FROM STDIN WITH (FORMAT csv, HEADER);'
  sed 's/\r$//' data/manual/localidad_sindicatura.csv  # el CSV usa CRLF
  echo '\.'
  cat db/sql/sindicaturas.sql
  echo 'COMMIT;'
} | docker compose exec -T db sh -c 'psql -q -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
