-- Pruebas de geo.reverse_geocode (Fase 3, "Pruebas mínimas" de docs/PLAN.md).
-- Se corren con tests/correr.sh. Cada prueba deja una fila en "resultado";
-- al final, el script falla si alguna no pasó.

CREATE TEMP TABLE resultado (prueba text, ok boolean, detalle text);

-- Atajo: geocodifica un punto en EPSG:6372.
CREATE FUNCTION pg_temp.rg(g geometry, lpr_max_m double precision DEFAULT 500) RETURNS jsonb
LANGUAGE sql STABLE AS $$
  SELECT geo.reverse_geocode(ST_X(t), ST_Y(t), lpr_max_m)::jsonb
  FROM (SELECT ST_Transform(g, 4326) AS t) s
$$;

-- 1. Cada localidad poligonal de Guasave: ST_PointOnSurface devuelve esa
--    localidad con poligono_localidad. Excepciones explícitas, con su motivo.
--    Con los datos del Marco 2022 no hay excepciones; si aparecen, se agregan
--    aquí con INSERT INTO excepcion_poligono VALUES ('<cvegeo>', '<motivo>').
CREATE TEMP TABLE excepcion_poligono (cvegeo text PRIMARY KEY, motivo text);

CREATE TEMP TABLE t1 AS
SELECT l.cvegeo, pg_temp.rg(ST_PointOnSurface(l.geom)) AS r
FROM geo.localidad l WHERE l.cve_mun = '011';

INSERT INTO resultado
SELECT '1. poligono_localidad en ST_PointOnSurface',
       count(*) FILTER (WHERE falla AND e.cvegeo IS NULL) = 0
         AND count(*) FILTER (WHERE NOT falla AND e.cvegeo IS NOT NULL) = 0,
       format('%s localidades; %s fallas no previstas: %s; %s excepciones que ya no fallan: %s',
              count(*),
              count(*) FILTER (WHERE falla AND e.cvegeo IS NULL),
              string_agg(t.cvegeo || '→' || coalesce(t.r->'localidad'->>'cvegeo', 'null') || ' ' || (t.r->>'metodo'), ', ')
                FILTER (WHERE falla AND e.cvegeo IS NULL),
              count(*) FILTER (WHERE NOT falla AND e.cvegeo IS NOT NULL),
              string_agg(t.cvegeo, ', ') FILTER (WHERE NOT falla AND e.cvegeo IS NOT NULL))
FROM (SELECT *, coalesce(r->'localidad'->>'cvegeo' <> cvegeo OR r->>'metodo' <> 'poligono_localidad', true) AS falla
      FROM t1) t
LEFT JOIN excepcion_poligono e USING (cvegeo);

-- 2. Cada localidad puntual de Guasave: un punto desplazado 50 m al norte
--    devuelve esa localidad con localidad_puntual y distancia_m de 50.
--    Se excluyen los puntos desplazados que caen a 1 m o menos de un polígono
--    (l, pe, pem) de Guasave, o fuera del municipio (localidades junto al
--    límite). Si otra localidad puntual queda más cerca que la propia, se
--    espera esa otra (regla 1.3) y se cuenta aparte.
CREATE TEMP TABLE t2 AS
SELECT left(lp.cvegeo, 9) AS cvegeo, q.g, pg_temp.rg(q.g) AS r,
       (SELECT left(o.cvegeo, 9) FROM geo.localidad_puntual o
        WHERE o.cve_mun = '011' AND ST_DWithin(o.geom, q.g, 50)
        ORDER BY ST_Distance(o.geom, q.g), o.cvegeo LIMIT 1) AS esperada
FROM geo.localidad_puntual lp, LATERAL (SELECT ST_Translate(lp.geom, 0, 50) AS g) q
WHERE lp.cve_mun = '011'
  AND ST_Contains((SELECT geom FROM geo.municipio WHERE cvegeo = '25011'), q.g)
  AND NOT EXISTS (SELECT 1 FROM geo.localidad l WHERE l.cve_mun = '011' AND ST_DWithin(l.geom, q.g, 1))
  AND NOT EXISTS (SELECT 1 FROM geo.poligono_externo pe WHERE pe.cve_mun = '011' AND ST_DWithin(pe.geom, q.g, 1))
  AND NOT EXISTS (SELECT 1 FROM geo.poligono_externo_manzana pm WHERE pm.cve_mun = '011' AND ST_DWithin(pm.geom, q.g, 1));

INSERT INTO resultado
SELECT '2. localidad_puntual a 50 m',
       count(*) FILTER (WHERE falla) = 0,
       format('%s de %s localidades puntuales probadas (las demás caen en un polígono o fuera de Guasave); '
              '%s con otra localidad puntual más cerca; fallas: %s %s',
              count(*), (SELECT count(*) FROM geo.localidad_puntual WHERE cve_mun = '011'),
              count(*) FILTER (WHERE esperada <> cvegeo),
              count(*) FILTER (WHERE falla),
              coalesce(string_agg(cvegeo || '→' || coalesce(r->'localidad'->>'cvegeo', 'null') || ' '
                                  || coalesce(r->>'distancia_m', 'null') || ' m', ', ') FILTER (WHERE falla), ''))
FROM (SELECT *, coalesce(r->'localidad'->>'cvegeo' <> esperada OR r->>'metodo' <> 'localidad_puntual'
                         OR abs((r->>'distancia_m')::numeric - ST_Distance(g, (SELECT geom FROM geo.localidad_puntual
                              WHERE left(cvegeo, 9) = esperada))::numeric) > 0.1
                         OR (esperada = cvegeo AND abs((r->>'distancia_m')::numeric - 50) > 0.1), true) AS falla
      FROM t2) t;

-- 3. Un punto alejado de toda localidad: fuera_de_localidad, sindicatura por Voronoi.
--    Se busca en una malla de 1 km dentro de Guasave el primer punto a más de
--    1 km de todo polígono de localidad y de todo punto lpr.
CREATE TEMP TABLE t3 AS
WITH m AS (SELECT geom FROM geo.municipio WHERE cvegeo = '25011'),
malla AS (
  SELECT ST_SetSRID(ST_MakePoint(x, y), 6372) AS g
  FROM m, generate_series(floor(ST_XMin(m.geom))::int, ceil(ST_XMax(m.geom))::int, 1000) x,
          generate_series(floor(ST_YMin(m.geom))::int, ceil(ST_YMax(m.geom))::int, 1000) y)
SELECT g, pg_temp.rg(g) AS r
FROM malla, m
WHERE ST_Contains(m.geom, malla.g)
  AND NOT EXISTS (SELECT 1 FROM geo.localidad l WHERE ST_DWithin(l.geom, malla.g, 1000))
  AND NOT EXISTS (SELECT 1 FROM geo.poligono_externo pe WHERE ST_DWithin(pe.geom, malla.g, 1000))
  AND NOT EXISTS (SELECT 1 FROM geo.poligono_externo_manzana pm WHERE ST_DWithin(pm.geom, malla.g, 1000))
  AND NOT EXISTS (SELECT 1 FROM geo.localidad_puntual lp WHERE ST_DWithin(lp.geom, malla.g, 1000))
ORDER BY ST_X(g), ST_Y(g)
LIMIT 1;

INSERT INTO resultado
SELECT '3. fuera_de_localidad con sindicatura por Voronoi',
       r->>'metodo' = 'fuera_de_localidad' AND r->'localidad' = 'null'::jsonb
         AND r->'sindicatura'->>'origen' = 'voronoi' AND r->'sindicatura'->>'nombre' IS NOT NULL
         AND r->'distancia_m' = 'null'::jsonb,
       format('punto %s: %s', ST_AsText(g), r)
FROM t3;

-- 4. Un punto en la ciudad de Guasave devuelve un AGEB urbano de 13 caracteres
--    que empieza con 250110001.
INSERT INTO resultado
SELECT '4. AGEB urbano en la ciudad de Guasave',
       r->'ageb'->>'tipo' = 'U' AND length(r->'ageb'->>'cvegeo') = 13 AND r->'ageb'->>'cvegeo' LIKE '250110001%',
       format('%s', r->'ageb')
FROM (SELECT pg_temp.rg(ST_PointOnSurface(geom)) AS r FROM geo.localidad WHERE cvegeo = '250110001') q;

-- 5. La parte de El Zopilote (250110291) fuera de Guasave devuelve el municipio vecino.
INSERT INTO resultado
SELECT '5. El Zopilote fuera de Guasave',
       r->'municipio'->>'cvegeo' <> '25011' AND (r->>'fuera_de_guasave')::boolean AND r->'localidad' = 'null'::jsonb,
       format('%s', r)
FROM (SELECT pg_temp.rg(ST_PointOnSurface(ST_Difference(l.geom, m.geom))) AS r
      FROM geo.localidad l, geo.municipio m
      WHERE l.cvegeo = '250110291' AND m.cvegeo = '25011') q;

-- 6. Otro municipio de Sinaloa (Culiacán): fuera_de_guasave. Fuera de Sinaloa
--    (Zócalo de la Ciudad de México) y coordenadas inválidas: sin resultado.
INSERT INTO resultado
SELECT '6a. otro municipio de Sinaloa',
       r->'municipio'->>'cvegeo' = '25006' AND (r->>'fuera_de_guasave')::boolean
         AND r->'sindicatura' = 'null'::jsonb AND r->'ageb' = 'null'::jsonb,
       format('%s', r)
FROM (SELECT pg_temp.rg(ST_PointOnSurface(geom)) AS r FROM geo.municipio WHERE cvegeo = '25006') q;

INSERT INTO resultado
SELECT '6b. fuera de Sinaloa y coordenadas inválidas',
       geo.reverse_geocode(-99.1332, 19.4326) IS NULL
         AND geo.reverse_geocode(-108.5, 95) IS NULL
         AND geo.reverse_geocode(200, 25.5) IS NULL
         AND geo.reverse_geocode(NULL, 25.5) IS NULL,
       'CDMX, lat 95, lon 200, lon NULL';

-- 7. El mismo punto consultado dos veces da exactamente la misma respuesta
--    (los puntos de la prueba 1).
INSERT INTO resultado
SELECT '7. determinismo',
       count(*) FILTER (WHERE pg_temp.rg(ST_PointOnSurface(l.geom)) IS DISTINCT FROM t1.r) = 0,
       format('%s puntos consultados de nuevo', count(*))
FROM t1 JOIN geo.localidad l USING (cvegeo);

-- Resumen
SELECT prueba, CASE WHEN ok THEN 'ok' ELSE 'FALLA' END AS estado, detalle FROM resultado ORDER BY prueba;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM resultado WHERE ok IS NOT TRUE) THEN
    RAISE EXCEPTION 'Hay pruebas que fallan';
  END IF;
END $$;
