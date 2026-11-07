-- Verificación de la Fase 2 (criterios de "Terminado cuando" en docs/PLAN.md).
-- Uso: docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < etl/verificar_sindicaturas.sql

\echo '1. Polígonos de sindicatura (deben ser 13, válidos y no vacíos)'
SELECT sindicatura, round((ST_Area(geom) / 1e6)::numeric, 2) AS km2,
       ST_NumGeometries(geom) AS partes, ST_IsValid(geom) AS valido
FROM geo.sindicatura_poligono ORDER BY sindicatura;

\echo '2. Cobertura del municipio: suma de áreas, huecos y traslapes'
WITH m AS (SELECT geom FROM geo.municipio WHERE cvegeo = '25011')
SELECT round((SELECT ST_Area(geom) FROM m)::numeric, 1) AS area_municipio_m2,
       round((SELECT sum(ST_Area(geom)) FROM geo.sindicatura_poligono)::numeric, 1) AS suma_areas_m2,
       round((100 * abs((SELECT sum(ST_Area(geom)) FROM geo.sindicatura_poligono) - (SELECT ST_Area(geom) FROM m))
              / (SELECT ST_Area(geom) FROM m))::numeric, 6) AS diferencia_pct,
       round((SELECT ST_Area(ST_Difference(m.geom, ST_Union(s.geom))) FROM geo.sindicatura_poligono s, m GROUP BY m.geom)::numeric, 3) AS huecos_m2,
       round((SELECT coalesce(sum(ST_Area(ST_Intersection(a.geom, b.geom))), 0)
              FROM geo.sindicatura_poligono a JOIN geo.sindicatura_poligono b
                ON a.sindicatura < b.sindicatura AND ST_Intersects(a.geom, b.geom))::numeric, 3) AS traslapes_m2;

\echo '3. Resumen del emparejamiento (localidades del INEGI en Guasave)'
SELECT origen, coalesce(metodo_match, '-') AS metodo_match, count(*) AS localidades
FROM geo.localidad_sindicatura GROUP BY ROLLUP (origen, metodo_match) ORDER BY 1, 2;

\echo '4. Localidades sin sindicatura (debe ser 0)'
SELECT count(*) AS sin_sindicatura FROM geo.localidad_sindicatura WHERE sindicatura IS NULL;

\echo '5. Localidades por sindicatura y origen'
SELECT sindicatura,
       count(*) FILTER (WHERE origen = 'implan') AS implan,
       count(*) FILTER (WHERE origen = 'voronoi') AS voronoi,
       count(*) AS total
FROM geo.localidad_sindicatura GROUP BY ROLLUP (sindicatura) ORDER BY sindicatura NULLS LAST;
