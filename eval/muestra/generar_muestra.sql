-- Fase 5: muestra de 400 puntos de control con semilla 2026 (docs/PLAN.md).
-- La corre eval/muestra/generar_muestra.sh, que escribe eval/muestra/puntos_control.csv.
--   numero_exterior (200): números exteriores de Guasave (INEGI 2023), al azar.
--   rural (150): al azar dentro del municipio y fuera de las localidades urbanas.
--   limite (50): al azar a menos de 100 m de un límite de localidad (capa l), por dentro o por fuera.
-- Las coordenadas se redondean a 6 decimales (~0.1 m) y los valores de referencia se
-- calculan sobre el punto ya redondeado.

CREATE TEMP TABLE guasave AS SELECT geom FROM geo.municipio WHERE cvegeo = '25011';

CREATE TEMP TABLE candidato (estrato text, orden int, geom geometry(Point, 6372), localidad_ne text);

-- Números exteriores: orden pseudoaleatorio con la semilla (md5 de la semilla y la
-- coordenada), independiente del orden físico de la tabla. Sin coordenadas repetidas
-- y solo dentro de Guasave (un punto de El Zopilote queda fuera).
INSERT INTO candidato
SELECT 'numero_exterior', row_number() OVER (ORDER BY md5('2026:' || ST_AsText(geom))), geom, localidad
FROM (SELECT DISTINCT ON (ST_AsText(n.geom)) n.geom, left(n.cvegeo, 9) AS localidad
      FROM geo.numero_exterior n, guasave g
      WHERE ST_Within(n.geom, g.geom)
      ORDER BY ST_AsText(n.geom), n.cvegeo) u;

-- Rural: municipio menos los polígonos de localidades urbanas.
INSERT INTO candidato
SELECT 'rural', d.path[1], d.geom, NULL
FROM guasave g,
     ST_Dump(ST_GeneratePoints(
       ST_Difference(g.geom, (SELECT ST_Union(geom) FROM geo.localidad WHERE cve_mun = '011' AND ambito = 'Urbana')),
       300, 2026)) d;

-- Límite: franja de 100 m a cada lado de los límites de localidad, dentro del municipio.
INSERT INTO candidato
SELECT 'limite', d.path[1], d.geom, NULL
FROM guasave g,
     ST_Dump(ST_GeneratePoints(
       ST_Intersection(g.geom, ST_Buffer((SELECT ST_Union(ST_Boundary(geom)) FROM geo.localidad WHERE cve_mun = '011'), 100)),
       100, 2026)) d;

-- Redondeo a 6 decimales en EPSG:4326 y punto redondeado de vuelta en EPSG:6372.
CREATE TEMP TABLE redondeado AS
SELECT c.estrato, c.orden, c.localidad_ne, w.lat, w.lon,
       ST_Transform(ST_SetSRID(ST_MakePoint(w.lon, w.lat), 4326), 6372) AS geom
FROM candidato c,
     LATERAL (SELECT ST_Transform(c.geom, 4326) AS g) t,
     LATERAL (SELECT round(ST_Y(t.g)::numeric, 6) AS lat, round(ST_X(t.g)::numeric, 6) AS lon) w;

-- Se toman los primeros de cada estrato que, ya redondeados, siguen cumpliendo su
-- condición, están dentro de Guasave y no repiten coordenada con otro punto.
CREATE TEMP TABLE muestra AS
WITH valido AS (
  SELECT r.* FROM redondeado r, guasave g
  WHERE ST_Within(r.geom, g.geom)
    AND (r.estrato <> 'rural' OR NOT EXISTS (
          SELECT 1 FROM geo.localidad l WHERE l.cve_mun = '011' AND l.ambito = 'Urbana' AND ST_Intersects(l.geom, r.geom)))
    AND (r.estrato <> 'limite' OR EXISTS (
          SELECT 1 FROM geo.localidad l WHERE l.cve_mun = '011' AND ST_DWithin(ST_Boundary(l.geom), r.geom, 100)))
), unico AS (
  SELECT DISTINCT ON (lat, lon) * FROM valido
  ORDER BY lat, lon, CASE estrato WHEN 'numero_exterior' THEN 1 WHEN 'rural' THEN 2 ELSE 3 END, orden
), numerado AS (
  SELECT *, row_number() OVER (PARTITION BY estrato ORDER BY orden) AS k FROM unico
)
SELECT * FROM numerado
WHERE k <= CASE estrato WHEN 'numero_exterior' THEN 200 WHEN 'rural' THEN 150 ELSE 50 END;

-- Localidad de referencia: la de la clave de manzana en numero_exterior; en los demás,
-- el polígono l, pe o pem que contiene el punto (l primero, como en las reglas 1.1 y 1.2;
-- luego menor área y clave). NULL si no cae en ninguna.
CREATE TEMP TABLE referencia AS
SELECT m.estrato, m.k, m.lat, m.lon,
       coalesce(m.localidad_ne, p.cvegeo) AS localidad_cvegeo
FROM muestra m
LEFT JOIN LATERAL (
  SELECT c.cvegeo FROM (
    SELECT 1 AS capa, cvegeo, geom FROM geo.localidad WHERE cve_mun = '011'
    UNION ALL SELECT 2, cvegeo, geom FROM geo.poligono_externo WHERE cve_mun = '011'
    UNION ALL SELECT 2, left(cvegeo, 9), geom FROM geo.poligono_externo_manzana WHERE cve_mun = '011') c
  WHERE m.localidad_ne IS NULL AND ST_Intersects(c.geom, m.geom)
  ORDER BY c.capa, ST_Area(c.geom), c.cvegeo LIMIT 1) p ON true;

-- Sindicatura de referencia (decisiones del usuario, docs/decisiones.md):
--   implan_tabla:       la localidad de referencia aparece en las tablas del IMPLAN.
--   implan_mapa:        si no, el polígono del IMPLAN digitalizado que contiene el punto
--                       (geo.sindicatura_implan, de data/manual/sindicaturas_implan.geojson).
--   implan_mapa_traslape: el punto cae en dos o más polígonos del IMPLAN; se guardan todas,
--                       separadas por "|", y cualquiera cuenta como acierto.
--   sin_cobertura_implan: no cae en ningún polígono del IMPLAN; sindicatura NULL y solo se
--                       evalúa el municipio.
COPY (
  WITH mapa AS (
    SELECT r.estrato, r.k, string_agg(s.sindicatura, '|' ORDER BY s.sindicatura) AS sindicaturas, count(s.*) AS n
    FROM referencia r
    LEFT JOIN geo.sindicatura_implan s
      ON ST_Intersects(s.geom, ST_Transform(ST_SetSRID(ST_MakePoint(r.lon, r.lat), 4326), 6372))
    GROUP BY 1, 2)
  SELECT row_number() OVER (ORDER BY CASE r.estrato WHEN 'numero_exterior' THEN 1 WHEN 'rural' THEN 2 ELSE 3 END, r.k) AS id,
         r.estrato, r.lat, r.lon,
         '25011' AS municipio_cvegeo, 'Guasave' AS municipio,
         coalesce(ls.sindicatura, ma.sindicaturas) AS sindicatura,
         CASE WHEN ls.sindicatura IS NOT NULL THEN 'implan_tabla'
              WHEN ma.n = 1 THEN 'implan_mapa'
              WHEN ma.n > 1 THEN 'implan_mapa_traslape'
              ELSE 'sin_cobertura_implan' END AS sindicatura_fuente,
         r.localidad_cvegeo, li.nombre_inegi AS localidad,
         CASE WHEN r.localidad_cvegeo IS NULL THEN NULL
              WHEN (SELECT ambito FROM geo.localidad WHERE cvegeo = r.localidad_cvegeo) = 'Urbana' THEN 'U' ELSE 'R' END AS localidad_ambito
  FROM referencia r
  JOIN mapa ma USING (estrato, k)
  LEFT JOIN geo.localidad_sindicatura li ON li.cvegeo = r.localidad_cvegeo
  LEFT JOIN geo.localidad_sindicatura ls ON ls.cvegeo = r.localidad_cvegeo AND ls.origen = 'implan'
  ORDER BY 1
) TO STDOUT WITH (FORMAT csv, HEADER);
