-- Fase 3: geocodificación inversa (reglas de asignación de docs/PLAN.md, tesis 7.4).
-- Devuelve los campos del contrato de la API como json (la atribución la agrega
-- la API), o NULL si las coordenadas no son válidas o el punto está fuera de
-- Sinaloa (la API responde 422).
-- Requiere las tablas de la Fase 1 y de la Fase 2 (etl/cargar_sindicaturas.sh).
-- Cargar: docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < db/sql/reverse_geocode.sql
--
-- Tolerancia de 1 m para huecos y traslapes entre capas (advertencia del INEGI).
-- Desempate en todas las reglas: menor distancia, luego menor área, luego clave.

CREATE OR REPLACE FUNCTION geo.reverse_geocode(lon double precision, lat double precision,
                                               lpr_max_m double precision DEFAULT 500)
RETURNS json
LANGUAGE plpgsql STABLE PARALLEL SAFE AS $$
DECLARE
  tol CONSTANT double precision := 1;
  p geometry;
  mun_cve text; mun_nom text;
  loc_cve text; metodo text; dist double precision;
  sind text; sind_origen text;
  ageb_cve text; ageb_tipo text;
BEGIN
  IF lon IS NULL OR lat IS NULL OR lon NOT BETWEEN -180 AND 180 OR lat NOT BETWEEN -90 AND 90 THEN
    RETURN NULL;
  END IF;
  p := ST_Transform(ST_SetSRID(ST_MakePoint(lon, lat), 4326), 6372);

  -- Regla 4. Municipio por cruce con mun, nunca de los atributos de la localidad.
  SELECT m.cvegeo, m.nomgeo INTO mun_cve, mun_nom
  FROM geo.municipio m
  WHERE ST_DWithin(m.geom, p, tol)
  ORDER BY ST_Distance(m.geom, p), ST_Area(m.geom), m.cvegeo
  LIMIT 1;
  IF mun_cve IS NULL THEN
    RETURN NULL;  -- fuera de Sinaloa
  END IF;
  IF mun_cve <> '25011' THEN
    RETURN json_build_object(
      'municipio', json_build_object('cvegeo', mun_cve, 'nombre', mun_nom),
      'fuera_de_guasave', true,
      'sindicatura', NULL, 'localidad', NULL, 'ageb', NULL, 'metodo', NULL, 'distancia_m', NULL);
  END IF;

  -- Regla 1. Localidad de Guasave; gana la primera subregla que aplique.
  -- 1.1 Polígono de localidad (l).
  SELECT l.cvegeo INTO loc_cve
  FROM geo.localidad l
  WHERE l.cve_mun = '011' AND ST_DWithin(l.geom, p, tol)
  ORDER BY ST_Distance(l.geom, p), ST_Area(l.geom), l.cvegeo
  LIMIT 1;
  IF loc_cve IS NOT NULL THEN
    metodo := 'poligono_localidad';
  ELSE
    -- 1.2 Polígono externo (pe, o pem con la clave de localidad de sus 9 primeros caracteres).
    SELECT c.cvegeo INTO loc_cve
    FROM (SELECT cvegeo, geom FROM geo.poligono_externo WHERE cve_mun = '011'
          UNION ALL
          SELECT left(cvegeo, 9), geom FROM geo.poligono_externo_manzana WHERE cve_mun = '011') c
    WHERE ST_DWithin(c.geom, p, tol)
    ORDER BY ST_Distance(c.geom, p), ST_Area(c.geom), c.cvegeo
    LIMIT 1;
    IF loc_cve IS NOT NULL THEN
      metodo := 'poligono_externo';
    ELSE
      -- 1.3 Localidad puntual (lpr) más cercana, a no más de lpr_max_m.
      SELECT left(lp.cvegeo, 9), ST_Distance(lp.geom, p) INTO loc_cve, dist
      FROM geo.localidad_puntual lp
      WHERE lp.cve_mun = '011' AND ST_DWithin(lp.geom, p, lpr_max_m)
      ORDER BY ST_Distance(lp.geom, p), lp.cvegeo
      LIMIT 1;
      -- 1.4 Ninguna.
      metodo := CASE WHEN loc_cve IS NULL THEN 'fuera_de_localidad' ELSE 'localidad_puntual' END;
    END IF;
  END IF;

  -- Regla 2. Sindicatura de la localidad si aparece en las tablas del IMPLAN;
  -- si no, el polígono de Voronoi que contiene el punto.
  SELECT ls.sindicatura, 'implan' INTO sind, sind_origen
  FROM geo.localidad_sindicatura ls
  WHERE ls.cvegeo = loc_cve AND ls.origen = 'implan';
  IF sind IS NULL THEN
    SELECT s.sindicatura, 'voronoi' INTO sind, sind_origen
    FROM geo.sindicatura_poligono s
    WHERE ST_DWithin(s.geom, p, tol)
    ORDER BY ST_Distance(s.geom, p), ST_Area(s.geom), s.sindicatura
    LIMIT 1;
  END IF;

  -- Regla 3. AGEB por cruce espacial; la urbana gana sobre la rural.
  SELECT a.cvegeo, 'U' INTO ageb_cve, ageb_tipo
  FROM geo.ageb_urbana a
  WHERE ST_DWithin(a.geom, p, tol)
  ORDER BY ST_Distance(a.geom, p), ST_Area(a.geom), a.cvegeo
  LIMIT 1;
  IF ageb_cve IS NULL THEN
    SELECT a.cvegeo, 'R' INTO ageb_cve, ageb_tipo
    FROM geo.ageb_rural a
    WHERE ST_DWithin(a.geom, p, tol)
    ORDER BY ST_Distance(a.geom, p), ST_Area(a.geom), a.cvegeo
    LIMIT 1;
  END IF;

  RETURN json_build_object(
    'municipio', json_build_object('cvegeo', mun_cve, 'nombre', mun_nom),
    'fuera_de_guasave', false,
    'sindicatura', CASE WHEN sind IS NOT NULL THEN json_build_object('nombre', sind, 'origen', sind_origen) END,
    'localidad', (SELECT json_build_object(
                    'cvegeo', ls.cvegeo, 'nombre', ls.nombre_inegi,
                    -- lpr son localidades rurales; las de l traen su ámbito.
                    'ambito', CASE (SELECT l.ambito FROM geo.localidad l WHERE l.cvegeo = ls.cvegeo)
                                WHEN 'Urbana' THEN 'U' ELSE 'R' END)
                  FROM geo.localidad_sindicatura ls WHERE ls.cvegeo = loc_cve),
    'ageb', CASE WHEN ageb_cve IS NOT NULL THEN json_build_object('cvegeo', ageb_cve, 'tipo', ageb_tipo) END,
    'metodo', metodo,
    'distancia_m', round(dist::numeric, 1));
END;
$$;
