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
