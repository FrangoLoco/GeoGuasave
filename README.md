# GeoGuasave

API REST de geocodificación inversa para el municipio de Guasave, Sinaloa. Recibe latitud y longitud y devuelve municipio, sindicatura, localidad, AGEB y clave geoestadística del INEGI.

Proyecto de tesis, Licenciatura en Ingeniería de Software, UAdeO Guasave. El plan de trabajo está en `docs/PLAN.md` y las decisiones en `docs/decisiones.md`.

## Requisitos

- Docker con Docker Compose.

## Puesta en marcha

```sh
cp .env.example .env          # y cambiar POSTGRES_PASSWORD
docker compose up -d --wait db
docker compose exec db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT postgis_full_version();"'
docker compose run --rm gdal ogrinfo --version
```

## Fuentes

INEGI, Marco Geoestadístico 2022; IMPLAN Guasave, Cartografía de sindicaturas.
