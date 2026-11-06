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
