# GeoGuasave

API REST de geocodificación inversa para el municipio de Guasave, Sinaloa (proyecto de tesis, Licenciatura en Ingeniería de Software, UAdeO Guasave). Recibe una latitud y una longitud y devuelve el municipio, la sindicatura, la localidad, el AGEB y la clave geoestadística del INEGI del punto.

El plan completo está en `docs/PLAN.md`: fases, contrato de la API, reglas de asignación, parámetros y qué cuenta como "terminado" en cada fase. Léelo antes de empezar cualquier fase.

## Cómo trabajamos

- Una fase a la vez. Al terminar una fase (o al llegar a un punto marcado como "Detente" en el plan), muestra la evidencia, es decir, los comandos que corriste y su salida, y espera mi confirmación antes de seguir.
- La tesis es la fuente de verdad. Si algo del plan no se puede hacer como está escrito, o los datos no coinciden con lo que dice, detente y pregúntame. No cambies la metodología por tu cuenta.
- Nunca inventes datos, claves, nombres de campos ni cifras. Si un archivo, campo o conteo no existe o no coincide con lo esperado, repórtalo tal cual.
- Cada decisión o parámetro nuevo se anota en `docs/decisiones.md` con fecha, decisión, motivo y alternativa descartada. Ese archivo alimenta el capítulo de resultados de la tesis.
- Todo debe poder reproducirse desde scripts. Nada de cambios a mano en la base de datos.
- Al cerrar una fase, propón un commit con un mensaje en español. No hagas push si no te lo pido.

## Fuera de alcance

- Geocodificación directa (de dirección a coordenada).
- Precisión a nivel de calle o de número exterior.

## Datos

- `data/raw/` guarda los zip del INEGI tal como se descargaron. No se modifican ni se suben a git.
- `data/manual/` guarda lo que se captura a mano: tablas del IMPLAN transcritas, revisiones de emparejamiento y el polígono de Bamoa digitalizado. Sí se sube a git.
- Antes de escribir SQL o scripts sobre una capa, inspecciónala con `ogrinfo -so` y usa los nombres reales de sus campos.
- El Marco Geoestadístico viene en EPSG:6372 (Lambert, ITRF2008). Las capas se guardan en 6372 para medir en metros; solo el punto de entrada se transforma desde EPSG:4326.
- El INEGI advierte huecos y traslapes de hasta 1 m entre capas. Usa una tolerancia de 1 m y un desempate determinista.
- Cada respuesta de la API incluye la atribución al INEGI (Marco Geoestadístico 2022) y al IMPLAN de Guasave.

## Stack

- PostgreSQL con PostGIS en Docker, con versión de imagen fija.
- GDAL en un contenedor para importar shapefiles; no se instala GDAL en la máquina.
- La lógica de geocodificación vive en una función SQL (`geo.reverse_geocode`), para que cualquier backend la reutilice y la comparación entre backends sea justa.
- Backend: Node.js con Fastify (`api/`), elegido en la Fase 4 con la prueba preliminar contra FastAPI (`bench/`).
- Pruebas de carga con k6 en contenedor (imagen `grafana/k6`).
- Los secretos (por ejemplo, la clave de Google Maps) van solo en `.env`, que nunca se sube. `.env.example` sí se sube.

## Comandos

<!-- Claude: actualiza esta sección al terminar cada fase con los comandos reales y probados. -->
- Levantar la base de datos: `cp .env.example .env` (una vez) y `docker compose up -d --wait db`
- Consola SQL: `docker compose exec db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'`
- Herramientas GDAL (montan `./data` en `/data`): `docker compose run --rm gdal ogrinfo --version`
- Cargar los datos del INEGI (requiere `data/raw/25_sinaloa.zip`, UPC 889463770541): `./etl/cargar_marco.sh`
- Verificar la carga: `docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < etl/verificar_marco.sql`
- Emparejar IMPLAN–INEGI (conserva la revisión manual): `python3 etl/emparejar_implan.py`
- Generar sindicaturas y Voronoi: `./etl/cargar_sindicaturas.sh`
- Verificar sindicaturas: `docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < etl/verificar_sindicaturas.sql`
- Digitalizar Bamoa del mapa del IMPLAN: `docker compose run --rm -q -v "$PWD/etl:/etl:ro" gdal python3 /etl/digitalizar_bamoa.py > data/manual/bamoa_implan.geojson`
- Validar con Bamoa: `./etl/validar_bamoa.sh`
- Cargar la función de geocodificación: `docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < db/sql/reverse_geocode.sql`
- Correr las pruebas (también recarga la función): `./tests/correr.sh`
- Levantar todo desde cero con los datos cargados (requiere `.env` y el zip): `./iniciar.sh`
- Pruebas de la API: `docker compose run --rm api npm test`
- Prueba preliminar de backend (k6): `./bench/correr.sh`
- Cargar los números exteriores 2023 (requiere `data/raw/794551086223_ss.zip`): `./etl/cargar_numeros_exteriores.sh`
- Digitalizar las 13 sindicaturas del IMPLAN: `docker compose run --rm -q -v "$PWD/etl:/etl:ro" gdal python3 /etl/digitalizar_sindicaturas.py > data/manual/sindicaturas_implan.geojson` (con `-u "$(id -u):$(id -g)" -e REVISION=/rev -v <carpeta>:/rev` deja imágenes de revisión)
- Generar la muestra de puntos de control: `./eval/muestra/generar_muestra.sh`

## Idioma

- Documentación, comentarios y mensajes de commit en español.
- Nombres de tablas y columnas en español y alineados con la tesis (localidad, sindicatura, ageb, municipio).
