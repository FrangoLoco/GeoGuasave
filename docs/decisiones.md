# Registro de decisiones

Cada entrada: fecha, decisión, motivo y alternativa descartada.

---

## 2026-11-05 — Versiones de PostGIS y GDAL

**Decisión.**
- Base de datos: imagen `postgis/postgis:17-3.5`, fijada por digest `sha256:01a6a70e41e6c4467c8f55f6063555ed72db2d6662cd0d571040d42eadaeb6f6`. Versiones reportadas por `postgis_full_version()`: PostgreSQL 17.5, PostGIS 3.5.2, GEOS 3.9.0, PROJ 7.2.1.
- Herramientas: imagen `ghcr.io/osgeo/gdal:ubuntu-small-3.10.3`, fijada por digest `sha256:dab45abca3ca83695d442018692f4f8a0f41955871c57e6101d7f89a92375caa`. GDAL 3.10.3, con los controladores ESRI Shapefile y PostgreSQL.

**Motivo.** Son versiones estables y recientes que ya estaban disponibles localmente o se descargaron sin problemas. Fijarlas por digest además del tag garantiza que la misma imagen se use en todas las corridas, aunque el tag `17-3.5` reciba parches. La variante `ubuntu-small` de GDAL incluye los controladores necesarios (Shapefile y PostgreSQL) con menor tamaño que `ubuntu-full`.

**Alternativa descartada.** Fijar solo por tag (`17-3.5`, `ubuntu-small-3.10.3`): el tag de PostGIS se mueve con cada versión menor de PostgreSQL y rompería la reproducibilidad.

## 2026-11-05 — Script de inicialización propio

**Decisión.** `db/init/` se monta sobre `/docker-entrypoint-initdb.d` y reemplaza el script de la imagen. Solo se crea la extensión `postgis` y el esquema `geo`.

**Motivo.** El script de la imagen también instala `postgis_topology`, `fuzzystrmatch` y `postgis_tiger_geocoder` (geocodificador de EE. UU.), que el proyecto no usa.

**Alternativa descartada.** Conservar el script de la imagen y agregar el esquema `geo` aparte.

## 2026-11-05 — Fuente del Marco Geoestadístico de Sinaloa

**Decisión.** La Fase 1 se carga desde `data/raw/25_sinaloa.zip`, descargado el 2026-11-05 de la ficha oficial del INEGI *Marco Geoestadístico, diciembre 2022* (UPC 889463770541):
`https://www.inegi.org.mx/contenidos/productos/prod_serv/contenidos/espanol/bvinegi/productos/geografia/marcogeo/889463770541/25_sinaloa.zip`
Tamaño: 79,036,726 bytes. SHA-256: `57d4242eebb9366e70a6f34ee8e0f2e39eaeb686e1da9e8849353ceb4aa99674`. GDAL lo lee sin descomprimir (`/vsizip/`).

**Motivo.** En `data/raw/` solo había una copia descomprimida e incompleta (sin `metadatos/`, sin `25m`, `25sia`, `25sil`, `25sip`, `25ti` ni `25fm.shx`) y con fechas de archivo de octubre de 2026. Se comparó byte a byte: los archivos `.shp`, `.shx`, `.dbf`, `.prj` y `.cpg` de las siete capas que usa el proyecto (`mun`, `l`, `pe`, `pem`, `lpr`, `a`, `ar`) son idénticos a los del zip oficial; la copia no tenía modificaciones, solo le faltaban archivos. Cargar desde el zip oficial con su hash permite reproducir la carga desde la fuente original.

**Alternativa descartada.** Cargar desde la carpeta descomprimida existente: el contenido es el mismo, pero no se puede verificar contra el original sin el zip.

## 2026-11-05 — Carga de las capas al esquema geo

**Decisión.**
- Script `etl/cargar_marco.sh` (ogr2ogr en el contenedor GDAL, lee el zip con `/vsizip/`, verifica primero el SHA-256) y `etl/post_carga.sql` (validación, reparación, índices GiST y `ANALYZE`). Es idempotente: `-overwrite` reemplaza cada tabla en cada corrida; se comprobó corriéndolo dos veces seguidas.
- Nombres de tabla en español: `mun` → `geo.municipio`, `l` → `geo.localidad`, `pe` → `geo.poligono_externo`, `pem` → `geo.poligono_externo_manzana`, `lpr` → `geo.localidad_puntual`, `a` → `geo.ageb_urbana`, `ar` → `geo.ageb_rural`. Los campos conservan el nombre del INEGI en minúsculas (`cvegeo`, `nomgeo`, `ambito`, …).
- Polígonos como `MultiPolygon` (`-nlt PROMOTE_TO_MULTI`), puntos como `Point`.
- SRID asignado con `-a_srs EPSG:6372`, sin reproyectar: `gdalsrsinfo -e` identifica el `.prj` de las siete capas como EPSG:6372.

**Motivo.** CLAUDE.md pide nombres de tablas en español alineados con la tesis. `-a_srs` evita una transformación innecesaria y garantiza que la columna quede registrada con SRID 6372.

**Alternativa descartada.** Usar los nombres de archivo del INEGI (`25l`, `25lpr`, …) como nombres de tabla; reproyectar con `-t_srs`.

## 2026-11-05 — Codificación de caracteres

**Decisión.** No se fuerza la codificación: GDAL la toma del `.cpg` de cada capa (UTF-8 en `l`, `pe`, `pem`, `a`; `ISO 88591` en `mun`, `lpr`, `ar`).

**Motivo.** Verificado tras la carga: 386 nombres con acentos en `localidad`, 1,723 en `localidad_puntual` y 3 en `municipio`, ninguno con caracteres sospechosos (`Ã`, `Â` o U+FFFD). No hizo falta reimportar.

**Alternativa descartada.** Forzar `-oo ENCODING=...` por capa: innecesario.

## 2026-11-05 — Geometrías reparadas

**Decisión.** Las geometrías inválidas se reparan con `ST_Multi(ST_CollectionExtract(ST_MakeValid(geom), 3))`, y cada reparación se registra en `geo.carga_reparaciones`.

**Resultado.** 3 geometrías reparadas, todas en `ageb_rural` y todas por autointersección de anillo: AGEB 250040368, 250011557 y 25011106A (esta última es de Guasave). El cambio de área es menor a 0.000001 m² en cada una. Las demás capas no tenían geometrías inválidas.

**Alternativa descartada.** `ST_Buffer(geom, 0)`: puede eliminar partes de un polígono con autointersecciones.

## 2026-11-05 — Localidades rurales que rebasan su AGEB (discrepancia con la tesis)

**Hallazgo.** La tesis dice que 15 localidades rurales de Guasave rebasan su AGEB. El catálogo del INEGI `localidades_rurales_que_rebasan_AGEB.csv` del zip lista **19** para Guasave (claves de localidad 0043, 0085, 0095, 0106, 0107, 0111, 0115, 0120, 0168, 0251, 0281, 0291, 0358, 0370, 0480, 0605, 0714, 0912, 0963). Con un cruce geométrico entre `localidad` y `ageb_rural`, contando solo los polígonos que entran más de 1 m en una segunda AGEB, resultan **12**. Las 7 restantes del catálogo tocan una segunda AGEB con áreas de 0 a 181 m², dentro de la tolerancia de 1 m que advierte el INEGI.

**Pendiente.** Confirmar con el autor de la tesis de dónde sale la cifra de 15. No afecta la metodología: la regla 3 obtiene el AGEB por cruce espacial y nunca de los atributos de la localidad.

## 2026-11-05 — Transcripción de las tablas del IMPLAN

**Decisión.** `data/manual/implan_localidades.csv` se genera con `etl/transcribir_implan.py` a partir de `data/manual/implan/implan/*.txt`, en lugar de capturarlo a mano. Los PDF del IMPLAN son de texto (generados con Word), y los TXT son idénticos byte a byte a la salida de `pdftotext -layout` de cada PDF (comprobado con `diff`).
- Por cada unidad, el script compara la suma de habitantes con el total impreso en la tabla y falla si no cuadra o si hay líneas que no puede leer.
- Dos celdas ocupan dos líneas en el PDF y se completan en el script, en el diccionario `CORRECCIONES` (verificadas con `pdftotext -raw`): Benito Juárez fila 1 (rango "Sindicatura y Comisaría") y San Rafael fila 1 (nombre "San Rafael (General Miguel Valle Dávalos)").
- Además de las columnas del plan (`unidad`, `localidad`, `rango`, `poblacion`), se agrega `num_implan`, el número de fila del original, para poder revisar la transcripción contra el PDF.
- Los nombres de localidad se conservan tal cual aparecen en el IMPLAN, incluidos "Ninguno [...]" y los nombres repetidos.

**Resultado.** 548 localidades en 13 unidades; las 13 sumas cuadran con los totales impresos (289,370 habitantes en total). Bamoa: 18 localidades y 7,963 habitantes, como dice la tesis. La numeración original salta algunos números (Alcaldía Central: 30 y 34; Bamoa: 12; El Burrión: 9; San Rafael: 16). Como los totales cuadran sin esas filas, se interpretan como saltos de numeración en el original, no como filas perdidas.

**Alternativa descartada.** Captura manual: no es reproducible y es más propensa a errores.

## 2026-11-05 — Emparejamiento IMPLAN–INEGI

**Decisión.** `etl/emparejar_implan.py`:
- Normalización solo para comparar: minúsculas, sin acentos, puntuación convertida en espacios y sin el prefijo "Ejido".
- Orden: coincidencia exacta normalizada en `l` de Guasave → exacta en `lpr` de Guasave → aproximada contra `l` + `lpr`.
- Coincidencia aproximada con `difflib.SequenceMatcher` (biblioteca estándar de Python), con puntaje de 0 a 100. **Umbral: 80.** Los casos aproximados no se aceptan solos: todos van a `revision_emparejamiento.csv` con sus 3 mejores candidatos.
- También van a revisión los nombres con más de un candidato exacto y las claves del INEGI que quedarían asignadas a dos o más filas del IMPLAN.
- Para facilitar la revisión, cada candidato lleva su distancia en km a la cabecera de la unidad (la fila 1 del IMPLAN, si se emparejó exactamente).

**Motivo.** El plan propone `rapidfuzz` como ejemplo; no está instalado y `difflib` resuelve lo mismo sin agregar una dependencia. El umbral solo decide si se propone un candidato; la decisión final es manual.

**Alternativa descartada.** `rapidfuzz` (agregaría una dependencia); aceptar automáticamente las coincidencias aproximadas por encima del umbral.

**Prueba de control (Bamoa).** La tesis dice que 10 de 18 coinciden por nombre exacto con la capa `l`. Resultado: 9 nombres de Bamoa tienen coincidencia exacta en `l`, de los cuales 7 quedan resueltos y 2 van a revisión (Choipa aparece también en La Trinidad; "Chino de los López" choca con "Ejido Chino de los López" al quitar el prefijo). Las otras 9 están en `lpr`. Las 18 localidades de Bamoa corresponden a 10 claves de `l` solo si se cuentan las dos variantes de Chino de los López (250110111 y 250110112). No se ajustó nada para llegar a 10; pendiente de confirmar con la tesis.

## 2026-11-06 — Revisión manual del emparejamiento

**Decisión.** Se resolvieron los 92 casos de `data/manual/revision_emparejamiento.csv`: 63 con clave elegida y 29 sin clave (`ninguna`), con el motivo en la columna `nota`. Los 16 casos marcados `[dudoso]` se aceptan como están, salvo Chino de los López.
- `250110112` "Ejido Chino de los López" se asigna a **Nío fila 9** ("Ejido Chino de los Lopéz", 366 hab., 5.4 km de la cabecera de Nío), no a Bamoa fila 16 ("Chino de los López", 5 hab., 7.0 km de la cabecera de Bamoa). Bamoa fila 16 queda sin clave. `250110111` "Chino de los López" es de El Burrión fila 4 (273 hab., 5.0 km de su cabecera).
- `etl/emparejar_implan.py` ahora conserva las columnas `cvegeo_elegido` y `nota` al volver a correr (antes las borraba) y agrega esas decisiones a `localidad_sindicatura.csv`: `aproximado` si se eligió el primer candidato de un caso aproximado, `manual` en cualquier otro caso. Falla si una clave elegida no es una localidad de Guasave o si una clave queda en dos filas del IMPLAN.

**Motivo.** Por nombre, población y distancia, `250110112` corresponde a Nío. Asignarla a Bamoa solo servía para acercarse a la cifra de la tesis, y no se ajustan datos para llegar a ella.

**Resultado.** 548 filas del IMPLAN: 456 exactas, 11 aproximadas, 52 manuales y 29 sin clave. En total, 519 claves, sin repetidas. Prueba de control de Bamoa: 8 claves en `l` (7 exactas más Choipa), contra 10 en la tesis. Se registra como discrepancia con la tesis.

**Alternativa descartada.** Asignar `250110112` a Bamoa fila 16 (9 claves en `l`, todavía no 10).

## 2026-11-06 — Polígonos de sindicatura por Voronoi

**Decisión.** `etl/cargar_sindicaturas.sh` carga `localidad_sindicatura.csv` y corre `db/sql/sindicaturas.sql`, que crea `geo.sindicatura_poligono` (13 polígonos) y `geo.localidad_sindicatura` (las 707 localidades del INEGI en Guasave, de `l` ∪ `lpr`, con su sindicatura y `origen`). Todo ocurre en una transacción y es idempotente: dos corridas dan el mismo hash.
- Generadores como en el plan: vértices de los bordes de `l`, `pe` y `pem` con `ST_Segmentize` a 50 m, más los puntos `lpr`, solo de localidades emparejadas con el IMPLAN. Las celdas se extienden 1 km más allá del rectángulo del municipio, se unen por sindicatura y se recortan con el polígono municipal.
- **Generadores compartidos.** 16 vértices son comunes a localidades vecinas de dos sindicaturas: Guasave / Callejones de Guasavito (Alcaldía Central / El Burrión, 6), Cruz Blanca / Gambino (Bamoa / Nío, 9) y La Cuerda / San Sebastián Número Dos (Estación Bamoa / Nío, 1). Se excluyen de los generadores, y la frontera entre ambas queda definida por los vértices vecinos.
- **Sindicatura de las 188 localidades sin IMPLAN** (`origen = 'voronoi'`): la del polígono más cercano a su punto representativo (`ST_PointOnSurface` de `l`, o el punto `lpr`). Si el punto está dentro, la distancia es 0. Si queda en un borde, gana el nombre en orden ascendente. Así se cubren puntos fuera del municipio, como El Zopilote. En la API, la regla 2 usa el polígono que contiene el punto consultado, no esta tabla.

**Motivo.** Un vértice compartido no puede generar una celda para dos sindicaturas, y elegir una de ellas sería arbitrario. El efecto se limita a la vecindad de esos vértices, donde además la API asigna primero por el polígono de la localidad (regla 1).

**Resultado.** 13 polígonos válidos; la suma de áreas es igual al área municipal (2,910.15 km², diferencia 0.000000 %), con 0 m² de huecos y 0 m² de traslapes. Tres sindicaturas tienen varias partes: Adolfo Ruiz Cortines (3), Alcaldía Central (2) y Estación Bamoa (3). Son enclaves alrededor de localidades del IMPLAN que quedan dentro del territorio de otra sindicatura, salvo una parte de 0.38 m² de Adolfo Ruiz Cortines, residuo del recorte por debajo de la tolerancia de 1 m.

**Alternativa descartada.** Asignar el vértice compartido a una sola sindicatura por orden alfabético.

## 2026-11-06 — Script de validación con Bamoa

**Decisión.** `etl/validar_bamoa.sh` carga `data/manual/bamoa_implan.geojson` en `geo.bamoa_implan` con ogr2ogr, reproyectado a EPSG:6372 desde el SRS que declare el archivo, y reporta intersección / área IMPLAN, intersección / área Voronoi e IoU. Si el archivo no existe, termina con un mensaje. Se probó con el propio polígono de Voronoi exportado a EPSG:4326 (resultado 1.0 en los tres índices) y luego se borró la prueba.

**Pendiente.** Digitalizar `bamoa_implan.geojson` en QGIS.

## 2026-11-06 — Digitalización del polígono de Bamoa del IMPLAN

**Decisión.** `data/manual/bamoa_implan.geojson` se genera con `etl/digitalizar_bamoa.py`, que corre en el contenedor GDAL (numpy y GDAL 3.10.3, imagen fijada por digest). No se traza a mano en QGIS.
- **Fuente.** Mapa "micro" de Bamoa en la página [Cartografía de sindicaturas del IMPLAN](https://guasave.gob.mx/implan/cartografia-de-sindicaturas/): `03 SIND. BAMOA MICRO.pdf`, descargado el 2026-11-06 y guardado en `data/manual/implan/mapas/` (SHA-256 `948b62adaf5b06867041f182f78948ace2092cde03c7a3a798a76b156fb78487`). Es una captura de Google Earth de 1920 × 1080 px con la "EXTENSION TERRITORIAL BAMOA" en verde translúcido y 11 localidades marcadas. El PDF de la tabla de Bamoa no trae mapa.
- **Georreferencia.** Transformación afín por mínimos cuadrados con los 11 marcadores. A cada uno le corresponde su punto `lpr` del INEGI, o `ST_PointOnSurface` de `l` en el caso de Bamoa, que no tiene `lpr`. El centro de cada marcador es el centroide de su color. **RMS 172.2 m, residuo máximo 273.9 m** (Norotillos), 16.3 × 15.7 m/px. Un ajuste de similitud con los mismos puntos da un RMS de 187.2 m.
- **Segmentación.** Píxeles con B/G < 0.6 y G − B > 35 (dentro: B/G ≈ 0.35; fuera: ≈ 0.85), filtro de mayoría de 9 × 9 y cierre morfológico de 31 px para rellenar las muescas de los marcadores y etiquetas dibujados sobre el borde. Después se vectoriza con `gdal.Polygonize`, se toma el polígono mayor sin huecos y se simplifica a 1 px (290 vértices, 66.45 km²). Área según el tamaño del cierre: sin cierre 64.73 km², 21 px 66.40, 31 px 66.45 y 41 px 66.51.
- Se revisó a ojo sobreponiendo el contorno al mapa original. Dos corridas dan el mismo archivo byte a byte.

**Motivo.** La segmentación por color es reproducible desde un script y sigue el borde del mapa con más fidelidad que un trazo manual. El cierre de 31 px cubre el diámetro de los marcadores del borde (~28 px), y el área varía 0.17 % entre 21 y 41 px.

**Alternativa descartada.**
- Georreferenciar con la línea negra de límite municipal del mapa: se comparó con `geo.municipio` y no coincide con el límite del INEGI 2022, del que se separa hasta ~1 km al sureste.
- Trazar a mano en QGIS: no es reproducible.

## 2026-11-06 — Resultado de la validación con Bamoa

**Resultado** (`./etl/validar_bamoa.sh`):

| | Valor |
|---|---|
| Área IMPLAN (digitalizada) | 66.45 km² |
| Área Voronoi | 73.79 km² |
| Intersección | 54.93 km² |
| Intersección / área IMPLAN | 0.8266 |
| Intersección / área Voronoi | 0.7444 |
| IoU | 0.6439 |

**Sensibilidad.** Al desplazar el polígono del IMPLAN una distancia igual al RMS de la georreferencia (172.2 m) en 8 direcciones, la IoU queda entre 0.6270 y 0.6557.

## 2026-11-06 — Función geo.reverse_geocode

**Decisión.** `db/sql/reverse_geocode.sql` define `geo.reverse_geocode(lon, lat, lpr_max_m DEFAULT 500)` en PL/pgSQL (`STABLE PARALLEL SAFE`).
- **Salida.** Devuelve `json` con los campos del contrato en su orden (`municipio`, `fuera_de_guasave`, `sindicatura`, `localidad`, `ageb`, `metodo`, `distancia_m`); la atribución la agrega la API. Devuelve `NULL` si las coordenadas no son válidas (nulas, longitud fuera de ±180 o latitud fuera de ±90) o si el punto está fuera de Sinaloa; la API responde 422 en ambos casos.
- **Tolerancia y desempate en todas las reglas.** Se usa la tolerancia de 1 m (`ST_DWithin(geom, p, 1)`) y el desempate del plan (menor distancia, luego menor área, luego clave) también para el municipio, el polígono de Voronoi y el AGEB, no solo para la localidad. En la regla 1.3 el área no aplica, porque son puntos.
- **Localidades solo de Guasave** (`cve_mun = '011'`): la función solo busca localidad para puntos dentro de Guasave, y así toda localidad devuelta tiene sindicatura.
- **AGEB urbana a 1 m o menos gana sobre la rural**, conforme a la regla 3 con la tolerancia general.
- **`ambito`:** `U` si la localidad está en `l` con ámbito "Urbana"; `R` en otro caso (`l` "Rural" o solo en `lpr`, que son localidades rurales puntuales).
- **`distancia_m`:** redondeada a 0.1 m.
- **Índices.** `etl/post_carga.sql` ahora crea un índice btree sobre `cvegeo` en las siete capas. La prueba 8 detectó un barrido secuencial de `geo.localidad` al buscar el ámbito por clave. Se volvió a correr `./etl/cargar_marco.sh` y `./etl/cargar_sindicaturas.sh`, y las tablas de sindicaturas dieron los mismos hashes que antes.

**Motivo.** Un solo criterio de tolerancia y desempate en todas las capas hace la función determinista frente a los huecos y traslapes de hasta 1 m que advierte el INEGI. `json` conserva el orden de las claves del contrato.

**Alternativa descartada.** Devolver un tipo compuesto (cada backend tendría que armar el JSON); buscar localidades de municipios vecinos (quedarían sin sindicatura).

## 2026-11-06 — Pruebas de la Fase 3

**Decisión.** Las pruebas son SQL (`tests/test_reverse_geocode.sql`) y las corre `tests/correr.sh`, que primero carga la versión de la función que está en el repositorio. No se agrega un framework (pgTAP): cada prueba deja una fila ok/FALLA y el script termina con error si alguna falla. La prueba 8 usa `auto_explain` con `log_nested_statements` para ver los planes de las consultas internas de la función.
- **Prueba 1.** Las 201 localidades poligonales devuelven su propia localidad en `ST_PointOnSurface`. No hubo excepciones; la lista explícita queda vacía.
- **Prueba 2.** Desplazamiento de 50 m al norte. Se excluyen los puntos que caen a 1 m o menos de un polígono y los que salen del municipio (3 localidades junto al límite: 250111135, 250111271 y 250111287). En 6 casos otra localidad puntual queda más cerca que la propia (de 37.5 a 49.9 m); ahí la prueba espera la más cercana, que es lo que dicta la regla 1.3. Se probaron 492 de 690.
- **Prueba 3.** El punto alejado se toma de una malla de 1 km: el primero a más de 1 km de toda localidad.

**Alternativa descartada.** pgTAP (otra extensión en la imagen) o pytest (dependencias en la máquina).

## 2026-11-06 — Configuración de la prueba preliminar de backend

**Decisión.** Hay dos prototipos mínimos de `GET /reverse` en `bench/`, uno con FastAPI y otro con Node.js. Ambos llaman a `geo.reverse_geocode` con un pool de 10 conexiones y devuelven tal cual el texto JSON de la función. Se miden con el mismo script de k6 (`bench/k6/reverse.js`, 50 usuarios virtuales, 1 minuto) y `bench/correr.sh` hace las 3 repeticiones.
- **FastAPI:** Python 3.12.16 (`python:3.12-slim`, fijada por digest), FastAPI 0.115.6, `uvicorn[standard]` 0.34.0 (uvloop y httptools) y asyncpg 0.30.0.
- **Node.js:** Node 22.23.4 (`node:22-slim`, fijada por digest), Fastify 5.2.0 y pg 8.13.1, con `package-lock.json`.
- **Framework de Node.** La tesis solo menciona Node.js y cita su documentación. Se usa Fastify por ser el análogo más cercano a FastAPI: validación de parámetros por esquema y OpenAPI mediante plugins, que la API final necesita. Ambos prototipos responden 422 con parámetros inválidos y con puntos fuera de Sinaloa.
- **Condiciones iguales.** Un proceso por prototipo, sin registro por solicitud. En cada corrida solo está levantado un prototipo, y se recrea desde cero. El orden se alterna (FastAPI–Node, Node–FastAPI, FastAPI–Node). k6 1.0.0 (fijada por digest) corre en un contenedor de la misma red de Compose.
- **Puntos de consulta.** `bench/puntos.json` tiene 1,000 coordenadas al azar dentro de Guasave (`ST_GeneratePoints` con semilla 2026). Cada iteración toma el siguiente punto en orden, así que ambos prototipos reciben la misma secuencia.
- **Máquina.** AMD Ryzen 5 5600U (12 hilos), 14 GB de RAM, Docker 29.9.3, Compose 5.7.0. Es la máquina de desarrollo, no el servidor de la corrida oficial.

**Motivo.** Comparar los dos backends en igualdad de condiciones: misma función SQL, mismo pool, mismo número de procesos y misma carga. Devolver el texto de la base sin volver a serializarlo deja la diferencia en el framework, el driver y el ciclo de eventos.

**Alternativa descartada.**
- Express: más común, pero sin validación por esquema integrada.
- `node:http` sin framework: la API final necesitaría reconstruir a mano la validación y OpenAPI.
- Varios workers por prototipo: agregaría otra variable a la comparación.

## 2026-11-06 — Resultado de la prueba preliminar de backend

**Resultado** (`./bench/correr.sh`; resúmenes de k6 en `bench/resultados/`). 50 usuarios virtuales durante 1 minuto por corrida, sin solicitudes fallidas en ninguna:

| Backend | Rep. | p95 (ms) | Mediana (ms) | Solicitudes/s | Solicitudes |
|---|---|---|---|---|---|
| FastAPI | 1 | 25.51 | 14.88 | 3,261.9 | 195,748 |
| FastAPI | 2 | 27.79 | 16.40 | 2,954.4 | 177,290 |
| FastAPI | 3 | 28.27 | 16.62 | 2,918.4 | 175,132 |
| **FastAPI** | **media** | **27.19** | | **3,044.9** | |
| Node.js | 1 | 10.99 | 9.09 | 5,310.5 | 318,669 |
| Node.js | 2 | 10.73 | 8.85 | 5,458.1 | 327,525 |
| Node.js | 3 | 11.21 | 9.28 | 5,206.5 | 312,429 |
| **Node.js** | **media** | **10.97** | | **5,325.0** | |

**Notas.**
- Hubo un primer intento que se detuvo: k6 no tenía permiso para escribir en `bench/resultados/`. Su única corrida completa (FastAPI, p95 24.39 ms, 3,385.2 solicitudes/s) no se cuenta, porque no quedó guardada. Desde entonces k6 corre con el usuario de la máquina.
- Durante la prueba había contenedores de otro proyecto (Supabase) corriendo en la misma máquina. El orden alternado reparte ese ruido entre ambos backends.

**Decisión (2026-11-06).** El usuario elige **Node.js (Fastify)** para la API final.

**Motivo.** En las tres repeticiones Node.js tuvo menor p95 (media de 10.97 ms contra 27.19 ms) y más solicitudes por segundo (5,325.0 contra 3,044.9), además de menos variación entre repeticiones.

**Alternativa descartada.** FastAPI.

## 2026-11-06 — API final (Node.js + Fastify)

**Decisión.** La API vive en `api/` (`src/app.js` y `src/server.js`). Corre en Node 22.23.4 (`node:22-slim`, fijada por digest) con usuario sin privilegios y `HEALTHCHECK` contra `/health`.
- **Dependencias** (exactas, con `package-lock.json`): fastify 5.12.7, @fastify/cors 10.1.0, @fastify/swagger 9.9.2, @fastify/swagger-ui 6.1.2 y pg 8.23.1. `npm audit --omit=dev`: 0 vulnerabilidades.
- **Contrato.** `GET /reverse` devuelve lo de `geo.reverse_geocode` más `atribucion`, con un esquema de respuesta que también documenta OpenAPI (`/docs`, `/docs/json`). Toda respuesta lleva la atribución, incluidos los errores y `/health`.
- **Errores.** 422 con `{error, detalle, atribucion}`: `parametros_invalidos` (latitud fuera de [−90, 90], longitud fuera de [−180, 180], valor no numérico o parámetro faltante) y `fuera_de_sinaloa` (la función devuelve `NULL`). 404 y 500 con el mismo formato.
- **`/health`.** Comprueba que la base responda y que existan `geo.reverse_geocode` y `geo.sindicatura_poligono`. Si falta algo responde 503 (`sin_datos` o `error`).
- **CORS** abierto (`origin: *`).
- **`LPR_MAX_DIST_M`** desde el entorno (500 por omisión). Si no es un número positivo, la API no arranca.
- **Registro.** Una línea JSON por solicitud (método, URL, estado y `ms`), en lugar de las dos de Fastify. Se desactivan con `LogController`, porque Fastify 5.12 marca `disableRequestLogging` como deprecada.
- **Pruebas** (`api/test/api.test.js`, con `node:test` integrado en Node): 10 pruebas contra la base real (contrato, igualdad con la función, 422, otro municipio, `LPR_MAX_DIST_M` a 250 y 500 m, `/health`, CORS, OpenAPI y registro).
- **Arranque.** `./iniciar.sh` levanta todo desde cero con los datos cargados (base, Marco, sindicaturas, función y API). La API se publica en `127.0.0.1:${API_PORT}`. Se comprobó con una copia limpia de los archivos del repositorio, otro nombre de proyecto y otros puertos, siguiendo solo el README: 22 s, `curl` con el contrato completo, 10 de 10 pruebas de la API y 8 de 8 de la función.

**Motivo.**
- Versiones. Las versiones de la prueba preliminar (fastify 5.2.0, @fastify/swagger-ui 5.2.0) tenían avisos de seguridad altos: validación evadible y recorrido de rutas en `@fastify/static`. Se eligieron las versiones más recientes que los corrigen y tienen al menos dos semanas publicadas. Los prototipos de `bench/` conservan las versiones que se midieron.
- `node:test` evita agregar un framework de pruebas.

**Alternativa descartada.** fastify 5.12.8 (publicada el 2026-11-02, con menos de dos semanas); @fastify/swagger-ui 5.2.6 (sigue dependiendo de una `@fastify/static` vulnerable).

## 2026-11-06 — Números exteriores 2023

**Decisión.** `etl/cargar_numeros_exteriores.sh` carga en `geo.numero_exterior` la capa `ne` de `data/raw/794551086223_ss.zip`: *Información vectorial de localidades amanzanadas y números exteriores 2023*, UPC 794551086223, SHA-256 `acdf3995184e7351ef78cfd720c0047db12e513b662455ab6b6567962b638ab0`, 854,919,485 bytes. Los campos se conservan tal cual, en minúsculas. El SRS se asigna como EPSG:6372, verificado con `gdalsrsinfo -e`. Se crean índices GiST y sobre `cvegeo`.

**Hallazgos.**
- El zip trae solo Guasave (109 carpetas de localidad amanzanada, todas `25011`), no todo Sinaloa como suponía el plan.
- La capa `ne` sí trae `CVEGEO`, la clave de manzana de 16 caracteres; el diccionario la describe como "Clave Geoestadística de Manzana". Sus primeros 9 caracteres dan la localidad.
- **Resultado de la carga:**
  - 80,048 números exteriores, todos con `CVEGEO` de 16 caracteres y prefijo `25011`.
  - Las 109 localidades tienen polígono en la capa `l` del Marco 2022 y sindicatura en las tablas del IMPLAN.
  - 59,484 puntos están en localidades urbanas y 20,564 en rurales.
  - Todos caen dentro del polígono `l` de su propia localidad.
  - Uno queda fuera del municipio: El Zopilote, `2501102910964026`.
- Las capas `l`, `a`, `m`, `fm` y `v` del producto provienen del Marco Geoestadístico 2022, según su `contenido.txt`.

## 2026-11-06 — Referencias de la muestra de puntos de control (decisiones del usuario)

**Decisión.**
1. **Localidad de referencia** en los estratos rural y límite: el polígono `l`, `pe` o `pem` que contiene el punto, sin tolerancia. `l` va primero, luego la menor área y luego la clave, como en las reglas 1.1 y 1.2. Si no cae en ninguno, es `null`.
2. **Sindicatura de referencia:**
   - Si la localidad de referencia aparece en las tablas del IMPLAN, la de esa tabla (`sindicatura_fuente = implan_tabla`).
   - Si no, la del polígono de sindicatura **digitalizado de los mapas del IMPLAN** (las 13 sindicaturas), no la del Voronoi.

**Motivo.** Fuera de las localidades urbanas quedan 2,858 km² y los polígonos rurales `l` cubren solo 42.8 km². Por eso casi todos los puntos rurales no caen en ninguna localidad. Usar el Voronoi como referencia compararía a GeoGuasave contra su propia construcción.

**Alternativa descartada.** El Voronoi como referencia, aclarando en la tesis que mide consistencia y no exactitud; sindicatura `null` en puntos sin localidad, evaluando solo el municipio; solo la capa `l` para la localidad de referencia.

## 2026-11-06 — Generación de la muestra de puntos de control

**Decisión.** `eval/muestra/generar_muestra.sh` corre `eval/muestra/generar_muestra.sql` y escribe `eval/muestra/puntos_control.csv`. Dos corridas dan el mismo archivo.
- **numero_exterior (200).** Orden pseudoaleatorio con la semilla: `md5('2026:' || coordenada)`. No depende del orden físico de la tabla. Se descartan coordenadas repetidas y puntos fuera de Guasave.
- **rural (150).** `ST_GeneratePoints(municipio − localidades urbanas, 300, 2026)`.
- **limite (50).** `ST_GeneratePoints(franja de 100 m a cada lado de los límites de los 201 polígonos l de Guasave ∩ municipio, 100, 2026)`.
- Se generan candidatos de sobra. Las coordenadas se redondean a 6 decimales (~0.1 m) y se toman los primeros de cada estrato que, ya redondeados, siguen dentro de Guasave, cumplen la condición de su estrato y no repiten coordenada. Las referencias se calculan sobre el punto redondeado.

**Resultado.**

| Criterio | Valor |
|---|---|
| Puntos (numero_exterior, rural, limite) | 400 (200, 150, 50) |
| Coordenadas repetidas | 0 |
| Dentro de Guasave (comprobado aparte en PostGIS) | 400 de 400 |
| numero_exterior en localidades urbanas / rurales (dato para H2) | 134 / 66 |
| rural con localidad / sin localidad | 4 / 146 |
| limite con localidad / sin localidad | 22 / 28 |
| Sindicatura de la tabla del IMPLAN / pendiente de los mapas | 226 / 174 |

**Pendiente.** Digitalizar los 13 mapas del IMPLAN y llenar la sindicatura de los 174 puntos marcados `pendiente_mapa_implan`.

## 2026-11-06 — Digitalización de las 13 sindicaturas del IMPLAN

**Decisión.** `etl/digitalizar_sindicaturas.py` (contenedor GDAL) genera `data/manual/sindicaturas_implan.geojson`. La configuración de cada mapa está en `data/manual/implan/mapas/digitalizacion.json`.
- **Mapas.** Los 26 mapas "micro" y "macro" de la [Cartografía de sindicaturas del IMPLAN](https://guasave.gob.mx/implan/cartografia-de-sindicaturas/), descargados el 2026-11-06 y guardados en `data/manual/implan/mapas/` con su nombre original. El SHA-256 se verifica antes de procesar cada uno. Se usan los 13 "micro"; los "macro" tienen el polígono tapado por marcadores y etiquetas.
- **Georreferencia.** Transformación afín con localidades marcadas en el mapa como puntos de control, cuya posición se lee a mano y el script afina al centroide de la mancha del marcador. Cada una se asocia a su punto `lpr`, o a `ST_PointOnSurface` de `l`. Se descarta de uno en uno el punto con residuo mayor a 500 m, porque son marcadores mal identificados (por ejemplo, "Los Hornos" en La Trinidad quedó a 1.7 km).
- **Segmentación.** Discriminante lineal de Fisher sobre ln(R/G), ln(B/G) e intensidad, entrenado con recuadros de muestra dentro y fuera del polígono. Luego un filtro de mayoría, una apertura morfológica opcional para cortar fugas por carreteras y zonas de color parecido, y un cierre morfológico para rellenar marcadores y etiquetas. Cada mapa se revisó sobreponiendo el contorno a la imagen. Se ajustaron muestras, exclusiones y apertura donde había fugas: Benito Juárez, León Fonseca (una laguna), San Rafael, Tamazula (mar y humedales) y Adolfo Ruiz Cortines.
- **Alcaldía Central se trazó a mano.** El verde translúcido sobre cultivos verdes no se separa por color, ni siquiera con rasgos de textura local. Se leyeron 7 vértices sobre el borde visible, con ayuda de una imagen del cociente de color suavizado, y se guardaron en `trazo`. La punta norte queda 28 px (~240 m) fuera del encuadre y se extrapoló como la intersección de los dos bordes rectos.

**Resultado.**

| Sindicatura | Puntos de control (usados / leídos) | RMS (m) | Área (km²) | Localidades de su tabla dentro |
|---|---|---|---|---|
| Adolfo Ruiz Cortines | 7 / 8 | 180.9 | 249.78 | 27 de 30 |
| Alcaldía Central (trazo) | 12 / 18 | 189.8 | 165.39 | 92 de 94 |
| Bamoa | 11 / 11 | 161.2 | 66.79 | 17 de 17 |
| Benito Juárez | 6 / 7 | 198.8 | 466.99 | 67 de 70 |
| El Burrión | 12 / 12 | 183.9 | 221.04 | 66 de 68 |
| Estación Bamoa | 6 / 6 | 118.6 | 102.49 | 9 de 10 |
| Juan José Ríos | 7 / 8 | 282.4 | 218.68 | 29 de 31 |
| La Brecha | 8 / 9 | 193.9 | 278.24 | 18 de 18 |
| La Trinidad | 10 / 11 | 193.8 | 156.56 | 40 de 42 |
| León Fonseca | 10 / 11 | 206.8 | 81.32 | 16 de 16 |
| Nío | 11 / 13 | 188.8 | 100.81 | 33 de 33 |
| San Rafael | 12 / 14 | 159.7 | 140.22 | 24 de 24 |
| Tamazula | 10 / 13 | 247.9 | 402.65 | 53 de 66 |

- **Validación independiente.** 488 de las 519 localidades de las tablas del IMPLAN (94 %) caen dentro del polígono digitalizado de su propia sindicatura.
- **Cobertura del municipio (2,910.2 km²).**
  - Los 13 polígonos cubren 2,517.4 km², el 86.5 %.
  - Quedan 392.8 km² sin cubrir, sobre todo la bahía y la costa del suroeste, que ningún mapa del IMPLAN incluye.
  - 50.1 km² quedan fuera del municipio.
  - Hay 83.6 km² de traslapes entre sindicaturas. El mayor es Adolfo Ruiz Cortines / Benito Juárez, con 45.5 km², y dentro hay localidades de ambas tablas (3 y 7): es un traslape del propio IMPLAN, no un error de digitalización.

**Limitaciones.**
- Los polígonos de Estación Bamoa (por el sur) y Tamazula (por el norte) tocan el borde de su imagen "micro" y pueden estar cortados. En los "macro" el polígono está tapado.
- Bamoa ya tenía su propia digitalización (`etl/digitalizar_bamoa.py`: 66.45 km², RMS 172.2 m), con la que se calculó la validación del commit 78559b3. La nueva da 66.79 km². Pendiente: decidir si `validar_bamoa.sh` usa la nueva.

**Alternativa descartada.** Trazar todo a mano en QGIS (no es reproducible); usar el Voronoi como referencia (es circular).

## 2026-11-06 — Sindicatura de referencia en traslapes y huecos del IMPLAN (decisiones del usuario)

**Decisión.** En `eval/muestra/generar_muestra.sql`, para los puntos cuya localidad de referencia no está en las tablas del IMPLAN:
- Si caen en un solo polígono del IMPLAN digitalizado: esa sindicatura (`implan_mapa`).
- Si caen en dos o más polígonos: se guardan todas, separadas por `|`, y **cualquiera cuenta como acierto** (`implan_mapa_traslape`).
- Si no caen en ninguno: sindicatura `NULL`, y **solo se evalúa el municipio** (`sin_cobertura_implan`).

**Resultado.**

| Fuente de la sindicatura de referencia | Puntos |
|---|---|
| `implan_tabla` | 226 |
| `implan_mapa` | 150 |
| `implan_mapa_traslape` | 6 |
| `sin_cobertura_implan` | 18 |

De los 18 sin cobertura, 13 están en la zona costera del suroeste, la mayoría en el AGEB rural 250110979, y 5 a menos de 600 m de algún polígono. Las coordenadas, las localidades y las 226 referencias de la tabla no cambiaron.

**Alternativa descartada.** Para los traslapes: excluir el punto de la evaluación de sindicatura, o elegir por centroide más cercano. Para los huecos: asignar el polígono más cercano, siempre o a 250 m o menos.

## 2026-11-07 — La validación con Bamoa usa la digitalización de las 13 sindicaturas (decisión del usuario)

**Decisión.** `etl/validar_bamoa.sh` toma ahora el polígono de Bamoa de `data/manual/sindicaturas_implan.geojson` (generado con `etl/digitalizar_sindicaturas.py`). Se borraron `etl/digitalizar_bamoa.py` y `data/manual/bamoa_implan.geojson`; siguen en el historial de git (commit 694f1c0 y anteriores). Así toda la cartografía del IMPLAN sale de una sola digitalización.

**Resultado** (`./etl/validar_bamoa.sh`), comparado con la digitalización anterior:

| | Anterior | Nueva |
|---|---|---|
| Área IMPLAN (digitalizada) | 66.45 km² | 66.79 km² |
| Área Voronoi | 73.79 km² | 73.79 km² |
| Intersección | 54.93 km² | 55.10 km² |
| Intersección / área IMPLAN | 0.8266 | 0.8250 |
| Intersección / área Voronoi | 0.7444 | 0.7467 |
| IoU | 0.6439 | 0.6446 |
| RMS de la georreferencia | 172.2 m | 161.2 m |
| IoU con desplazamiento de un RMS (8 direcciones) | 0.6270–0.6557 | 0.6288–0.6550 |

La diferencia en IoU es de 0.0007, muy por debajo del rango que produce la georreferencia.

**Alternativa descartada.** Conservar la digitalización propia de Bamoa: daba casi el mismo resultado, pero dejaba dos versiones del mismo polígono.

## 2026-11-09 — Consulta de los 400 puntos (Instrumento 1, paso 1)

**Resultado** (`python3 eval/muestra/consultar.py`): 400 respuestas de GeoGuasave, 400 de Nominatim (`format=jsonv2`, `accept-language=es`, una solicitud cada 1.1 s) y 400 de la Geocoding API de Google (`language=es`), todas con `status` `OK`. Las respuestas crudas, con su fecha de consulta, están en `data/eval_raw/` (no se suben a git). Consultas del 2026-11-09.

## 2026-11-09 — Extracción de nombres de Google y Nominatim (Instrumento 1, paso 2)

**Decisión.** En `eval/muestra/emparejar_respuestas.py`:
- **Google:** la localidad es el componente `locality` del primer resultado (el más específico que devuelve la API); si no lo trae, `sublocality`. El municipio es el `administrative_area_level_2` del primer resultado que lo traiga (el primer resultado nunca lo trae).
- **Nominatim:** la localidad es el primer campo que exista de `hamlet`, `village`, `town` y `city`, del más específico al menos; el municipio es `county`. En 48 respuestas hay dos campos (por ejemplo, `hamlet` y el `village` que lo contiene); se toma el más específico.
- **Emparejamiento:** la normalización de `etl/emparejar_implan.py` (minúsculas, sin acentos ni puntuación, sin el prefijo "Ejido") contra las localidades de Guasave en `l` y `lpr`. Un solo candidato exacto se acepta; los homónimos (una fila por punto) y los nombres sin coincidencia exacta (una fila por nombre) van a `data/manual/revision_respuestas.csv`. Para ordenar los candidatos de revisión, el puntaje es el mayor entre el nombre completo y el nombre sin el texto entre paréntesis, y la distancia al punto desempata; esto solo ordena, no decide.
- **Sindicatura** de Google y Nominatim: la de su localidad en la tabla del IMPLAN (`data/manual/localidad_sindicatura.csv`); vacía si la localidad no está en la tabla.

**Motivo.** Es el criterio del plan (Fase 6a) y de la tesis (nombres normalizados, emparejados con el catálogo y revisión manual de los ambiguos); el campo más específico es el que cada servicio presenta como su respuesta.

**Alternativa descartada.** Contar acierto si cualquiera de los nombres de la respuesta coincide (infla la tasa); usar todos los resultados de Google y no solo el primero; aceptar en automático la coincidencia sin paréntesis o el homónimo más cercano (la tesis pide revisión manual de los ambiguos).

## 2026-11-09 — Revisión de las respuestas de Google y Nominatim (propuestas aceptadas por el usuario)

**Decisión.** El usuario pidió que Claude llenara `data/manual/revision_respuestas.csv` con propuestas. Cada fila lleva su criterio en `nota`:
- **Homónimos (20):** el candidato más cercano al punto.
- **Mismo nombre sin el paréntesis del INEGI (24):** por ejemplo, "Gabriel Leyva Solano" → "Gabriel Leyva Solano (Benito Juárez)". 17 a menos de 1 km y 7 entre 1 y 3.1 km.
- **Variante de prefijo, sufijo u ortografía (10)**, a 1.8 km o menos: por ejemplo, "Colonia 24 de Febrero" → "24 de Febrero" y "El Rojo Gómez" → "Javier Rojo Gómez".
- **Dudosas (3), marcadas "PROPUESTA DUDOSA"** para que el usuario las confirme: "Campo Preciado La Sabanilla", "Las Cañadas" y "San Francisco de Capomos".
- **`ninguna` (17):** el nombre no corresponde a ninguna localidad de Guasave; el mejor candidato tiene un nombre distinto y está a 3.8 km o más (por ejemplo, "Cangilones", "Navachiste" y "Centro"). Cuenta como fallo a nivel de localidad y de sindicatura.

**Motivo.** Ahorrar la revisión de casos con una respuesta evidente, dejando el criterio a la vista en cada fila.

**Alternativa descartada.** Revisar a mano los 73 casos.

## 2026-11-09 — Puntos donde Google devuelve el municipio Juan José Ríos (decisión del usuario)

**Hecho.** En 37 de los 400 puntos, Google devuelve `administrative_area_level_2` = "Juan José Ríos" en lugar de Guasave. En 34 de ellos la sindicatura de referencia es Juan José Ríos y en 3 es Adolfo Ruiz Cortines. Según el usuario, el Congreso del Estado de Sinaloa aprobó Juan José Ríos como municipio el 5 de marzo de 2021, y su ayuntamiento entró en funciones el 1 de noviembre de 2024. El Marco Geoestadístico 2022 del INEGI, que es la referencia, todavía lo incluye en Guasave. La cartografía de sindicaturas del IMPLAN es de 2020: así aparece en el menú "Banco de proyectos" de su página, "Cartografía De Sindicaturas (2020)" (https://guasave.gob.mx/implan/cartografia-de-sindicaturas/, consultada el 2026-11-09). Los PDF descargados tienen fecha de modificación del 14 y 15 de noviembre de 2023, que es la de exportación del archivo, no necesariamente la de los datos). Las dos referencias son anteriores a que el municipio entrara en funciones.

**Decisión.** Estos 37 puntos se tratan aparte a nivel municipio. Salen de la tasa de acierto de municipio de los tres servicios, para que la comparación siga siendo pareada (n = 363), y se reportan en una tabla separada. A nivel de sindicatura y de localidad se evalúan igual que los demás. Los 2 puntos donde Nominatim devuelve "Municipio de Sinaloa" sí cuentan como error.

**Motivo.** Google refleja una división municipal posterior a la referencia. Contarlo como error castigaría una respuesta que hoy es correcta, y contarlo como acierto contradiría la referencia oficial que usa el estudio.

**Alternativa descartada.** Contarlos como error, que es lo literal según el INEGI 2022, o como acierto.
