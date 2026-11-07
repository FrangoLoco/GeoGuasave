-- Fase 2, pasos 3 y 4: sindicatura de cada localidad del INEGI en Guasave y
-- polígonos de sindicatura por Voronoi.
-- Lo corre etl/cargar_sindicaturas.sh, que antes llena la tabla temporal
-- "implan" con data/manual/localidad_sindicatura.csv.

-- Localidades del INEGI en Guasave: capa l más capa lpr (clave de 9 caracteres).
CREATE TEMP TABLE inegi AS
SELECT cvegeo, nomgeo FROM geo.localidad WHERE cve_mun = '011'
UNION
SELECT left(cvegeo, 9), nomgeo FROM geo.localidad_puntual WHERE cve_mun = '011'
  AND left(cvegeo, 9) NOT IN (SELECT cvegeo FROM geo.localidad WHERE cve_mun = '011');

DO $$
BEGIN
  IF EXISTS (SELECT cvegeo FROM implan EXCEPT SELECT cvegeo FROM inegi) THEN
    RAISE EXCEPTION 'localidad_sindicatura.csv tiene claves que no son localidades de Guasave';
  END IF;
END $$;

-- Generadores: vértices de los bordes de l, pe y pem densificados cada 50 m,
-- más los puntos lpr, solo de localidades con sindicatura del IMPLAN.
CREATE TEMP TABLE generador AS
WITH poligonos AS (
  SELECT cvegeo, geom FROM geo.localidad WHERE cve_mun = '011'
  UNION ALL SELECT cvegeo, geom FROM geo.poligono_externo WHERE cve_mun = '011'
  UNION ALL SELECT left(cvegeo, 9), geom FROM geo.poligono_externo_manzana WHERE cve_mun = '011'
), puntos AS (
  SELECT cvegeo, (ST_DumpPoints(ST_Segmentize(ST_Boundary(geom), 50))).geom AS geom FROM poligonos
  UNION ALL
  SELECT left(cvegeo, 9), geom FROM geo.localidad_puntual WHERE cve_mun = '011'
)
SELECT DISTINCT ON (ST_AsBinary(p.geom), i.unidad) i.unidad, p.geom
FROM puntos p JOIN implan i USING (cvegeo);

-- Un vértice compartido por localidades vecinas de dos sindicaturas no puede
-- generar una celda para ambas: se excluye (ver docs/decisiones.md).
CREATE TEMP TABLE generador_excluido AS
SELECT ST_AsBinary(geom) AS wkb, string_agg(unidad, ' / ' ORDER BY unidad) AS sindicaturas
FROM generador GROUP BY 1 HAVING count(*) > 1;
DELETE FROM generador WHERE ST_AsBinary(geom) IN (SELECT wkb FROM generador_excluido);
SELECT sindicaturas, count(*) AS generadores_excluidos FROM generador_excluido GROUP BY 1 ORDER BY 1;

CREATE INDEX ON generador USING gist (geom);

-- Celdas de Voronoi, extendidas más allá del municipio para que lo cubran completo.
CREATE TEMP TABLE celda AS
SELECT (ST_Dump(ST_VoronoiPolygons(ST_Collect(g.geom), 0,
          (SELECT ST_Expand(geom, 1000) FROM geo.municipio WHERE cvegeo = '25011')))).geom AS geom
FROM generador g;

CREATE INDEX ON celda USING gist (geom);

-- Cada celda contiene exactamente un generador; se une por sindicatura y se
-- recorta al polígono municipal.
DROP TABLE IF EXISTS geo.sindicatura_poligono;
CREATE TABLE geo.sindicatura_poligono AS
SELECT g.unidad AS sindicatura,
       ST_Multi(ST_CollectionExtract(ST_Intersection(ST_Union(c.geom), m.geom), 3))::geometry(MultiPolygon, 6372) AS geom
FROM celda c
JOIN generador g ON ST_Intersects(c.geom, g.geom)
CROSS JOIN (SELECT geom FROM geo.municipio WHERE cvegeo = '25011') m
GROUP BY g.unidad, m.geom;

ALTER TABLE geo.sindicatura_poligono ADD PRIMARY KEY (sindicatura);
CREATE INDEX sindicatura_poligono_geom_gist ON geo.sindicatura_poligono USING gist (geom);

-- Sindicatura de cada localidad: la del IMPLAN si aparece en sus tablas; si no,
-- la del polígono de Voronoi que contiene el punto representativo de la
-- localidad (ST_PointOnSurface de l, o el punto lpr).
DROP TABLE IF EXISTS geo.localidad_sindicatura;
CREATE TABLE geo.localidad_sindicatura AS
WITH punto AS (
  SELECT cvegeo, ST_PointOnSurface(geom) AS geom FROM geo.localidad WHERE cve_mun = '011'
  UNION ALL
  SELECT left(cvegeo, 9), geom FROM geo.localidad_puntual WHERE cve_mun = '011'
    AND left(cvegeo, 9) NOT IN (SELECT cvegeo FROM geo.localidad WHERE cve_mun = '011')
)
SELECT n.cvegeo, n.nomgeo AS nombre_inegi,
       coalesce(i.unidad, v.sindicatura) AS sindicatura,
       CASE WHEN i.cvegeo IS NULL THEN 'voronoi' ELSE 'implan' END AS origen,
       i.nombre_implan, i.metodo_match, i.puntaje
FROM inegi n
JOIN punto p USING (cvegeo)
LEFT JOIN implan i USING (cvegeo)
-- El polígono más cercano (distancia 0 si lo contiene; un punto puede quedar
-- fuera del municipio, como en El Zopilote). Empate en un borde: nombre ascendente.
LEFT JOIN LATERAL (
  SELECT s.sindicatura FROM geo.sindicatura_poligono s
  ORDER BY ST_Distance(s.geom, p.geom), s.sindicatura LIMIT 1
) v ON true;

ALTER TABLE geo.localidad_sindicatura ADD PRIMARY KEY (cvegeo);
ANALYZE geo.sindicatura_poligono;
ANALYZE geo.localidad_sindicatura;
