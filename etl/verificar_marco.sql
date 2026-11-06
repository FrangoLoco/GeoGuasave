-- Verificaciones de la Fase 1 (docs/PLAN.md). Solo lectura.
-- Uso: docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < etl/verificar_marco.sql

\echo '1. Conteo por capa: Sinaloa y Guasave (cve_mun = 011)'
SELECT 'municipio' AS tabla, count(*) AS sinaloa, count(*) FILTER (WHERE cve_mun = '011') AS guasave FROM geo.municipio
UNION ALL SELECT 'localidad', count(*), count(*) FILTER (WHERE cve_mun = '011') FROM geo.localidad
UNION ALL SELECT 'poligono_externo', count(*), count(*) FILTER (WHERE cve_mun = '011') FROM geo.poligono_externo
UNION ALL SELECT 'poligono_externo_manzana', count(*), count(*) FILTER (WHERE cve_mun = '011') FROM geo.poligono_externo_manzana
UNION ALL SELECT 'localidad_puntual', count(*), count(*) FILTER (WHERE cve_mun = '011') FROM geo.localidad_puntual
UNION ALL SELECT 'ageb_urbana', count(*), count(*) FILTER (WHERE cve_mun = '011') FROM geo.ageb_urbana
UNION ALL SELECT 'ageb_rural', count(*), count(*) FILTER (WHERE cve_mun = '011') FROM geo.ageb_rural;

\echo '2. Localidades poligonales (capa l) de Guasave por ámbito. Tesis: 201 = 17 urbanas + 184 rurales'
SELECT ambito, count(*) FROM geo.localidad WHERE cve_mun = '011' GROUP BY ROLLUP (ambito) ORDER BY ambito;

\echo '3. El Zopilote (250110291) frente al polígono municipal de Guasave'
SELECT l.cvegeo, l.nomgeo,
       ST_Within(l.geom, m.geom) AS contenida_en_guasave,
       round(ST_Area(l.geom)::numeric) AS area_m2,
       round(ST_Area(ST_Difference(l.geom, m.geom))::numeric) AS area_fuera_m2,
       (SELECT string_agg(m2.cvegeo || ' ' || m2.nomgeo, ', ')
          FROM geo.municipio m2 WHERE m2.cvegeo <> '25011' AND ST_Intersects(l.geom, m2.geom)) AS otros_municipios
FROM geo.localidad l, geo.municipio m
WHERE l.cvegeo = '250110291' AND m.cvegeo = '25011';

\echo '4. Localidades rurales de Guasave cuyo polígono entra más de 1 m en dos o más AGEB rurales'
WITH x AS (
  SELECT l.cvegeo, l.nomgeo, count(*) AS agebs, string_agg(ar.cve_ageb, ',' ORDER BY ar.cve_ageb) AS cve_agebs
  FROM geo.localidad l
  JOIN geo.ageb_rural ar ON ST_Intersects(l.geom, ST_Buffer(ar.geom, -1))
  WHERE l.cve_mun = '011' AND l.ambito = 'Rural'
  GROUP BY l.cvegeo, l.nomgeo
)
SELECT * FROM x WHERE agebs > 1 ORDER BY cvegeo;

\echo '5. SRID y validez de todas las geometrías'
SELECT 'municipio' AS tabla, array_agg(DISTINCT ST_SRID(geom)) AS srid, count(*) FILTER (WHERE NOT ST_IsValid(geom)) AS invalidas FROM geo.municipio
UNION ALL SELECT 'localidad', array_agg(DISTINCT ST_SRID(geom)), count(*) FILTER (WHERE NOT ST_IsValid(geom)) FROM geo.localidad
UNION ALL SELECT 'poligono_externo', array_agg(DISTINCT ST_SRID(geom)), count(*) FILTER (WHERE NOT ST_IsValid(geom)) FROM geo.poligono_externo
UNION ALL SELECT 'poligono_externo_manzana', array_agg(DISTINCT ST_SRID(geom)), count(*) FILTER (WHERE NOT ST_IsValid(geom)) FROM geo.poligono_externo_manzana
UNION ALL SELECT 'localidad_puntual', array_agg(DISTINCT ST_SRID(geom)), count(*) FILTER (WHERE NOT ST_IsValid(geom)) FROM geo.localidad_puntual
UNION ALL SELECT 'ageb_urbana', array_agg(DISTINCT ST_SRID(geom)), count(*) FILTER (WHERE NOT ST_IsValid(geom)) FROM geo.ageb_urbana
UNION ALL SELECT 'ageb_rural', array_agg(DISTINCT ST_SRID(geom)), count(*) FILTER (WHERE NOT ST_IsValid(geom)) FROM geo.ageb_rural;

\echo '6. Codificación: nombres con caracteres fuera de ASCII y posibles errores (Ã, Â o U+FFFD)'
SELECT tabla, count(*) FILTER (WHERE nomgeo ~ '[^\x01-\x7F]') AS con_acentos,
       count(*) FILTER (WHERE nomgeo ~ '[ÃÂ]' OR nomgeo LIKE '%' || chr(65533) || '%') AS sospechosos
FROM (SELECT 'municipio' AS tabla, nomgeo FROM geo.municipio
      UNION ALL SELECT 'localidad', nomgeo FROM geo.localidad
      UNION ALL SELECT 'localidad_puntual', nomgeo FROM geo.localidad_puntual) t
GROUP BY tabla ORDER BY tabla;
SELECT nomgeo FROM geo.localidad WHERE cve_mun = '011' AND nomgeo ~ '[ñÑáéíóúÁÉÍÓÚü]' ORDER BY nomgeo LIMIT 8;
