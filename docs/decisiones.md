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
