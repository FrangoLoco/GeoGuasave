# GeoGuasave

API REST de geocodificación inversa para el municipio de Guasave, Sinaloa. Recibe latitud y longitud y devuelve municipio, sindicatura, localidad, AGEB y clave geoestadística del INEGI.

Proyecto de tesis, Licenciatura en Ingeniería de Software, UAdeO Guasave. El plan de trabajo está en `docs/PLAN.md` y las decisiones en `docs/decisiones.md`.

## Requisitos

- Docker con Docker Compose.

## Puesta en marcha

1. Descarga `25_sinaloa.zip` de la ficha del INEGI *Marco Geoestadístico, diciembre 2022* (UPC 889463770541) y déjalo en `data/raw/` sin descomprimir.
2. Levanta todo con los datos cargados:

```sh
cp .env.example .env          # y cambiar POSTGRES_PASSWORD
./iniciar.sh
```

`iniciar.sh` levanta PostgreSQL con PostGIS, carga el Marco Geoestadístico, genera las sindicaturas (tablas del IMPLAN + polígonos de Voronoi), crea la función `geo.reverse_geocode` y arranca la API. Se puede volver a correr: recarga los datos desde cero.

## Uso

```sh
curl 'http://127.0.0.1:8000/reverse?lat=25.5674&lon=-108.4697'
```

```json
{"municipio":{"cvegeo":"25011","nombre":"Guasave"},"fuera_de_guasave":false,
 "sindicatura":{"nombre":"Alcaldía Central","origen":"implan"},
 "localidad":{"cvegeo":"250110001","nombre":"Guasave","ambito":"U"},
 "ageb":{"cvegeo":"2501100010019","tipo":"U"},"metodo":"poligono_localidad","distancia_m":null,
 "atribucion":"Fuente: INEGI, Marco Geoestadístico 2022; IMPLAN Guasave, Cartografía de sindicaturas."}
```

- `GET /reverse?lat=&lon=`: municipio, sindicatura, localidad y AGEB del punto. Responde 422 con coordenadas inválidas o fuera de Sinaloa. Un punto de otro municipio de Sinaloa responde con `fuera_de_guasave: true`.
- `GET /health`: estado de la API y de la base de datos.
- `GET /docs`: documentación OpenAPI.

Configuración en `.env`: `API_PORT` (8000) y `LPR_MAX_DIST_M`, la distancia máxima en metros a una localidad puntual (500).

## Pruebas

```sh
./tests/correr.sh                       # función SQL geo.reverse_geocode
docker compose run --rm api npm test    # API
```

## Fuentes

INEGI, Marco Geoestadístico 2022; IMPLAN Guasave, Cartografía de sindicaturas.
