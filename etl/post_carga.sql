-- Validación, reparación, índices y ANALYZE de las capas del Marco Geoestadístico.
-- Lo ejecuta etl/cargar_marco.sh después de importar.

-- Registro de geometrías reparadas en la última carga (se recrea en cada corrida).
DROP TABLE IF EXISTS geo.carga_reparaciones;
CREATE TABLE geo.carga_reparaciones (
  tabla        text,
  id           integer,
  cvegeo       text,
  motivo       text,
  area_antes   double precision,
  area_despues double precision
);

DO $$
DECLARE
  t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['municipio','localidad','poligono_externo',
                           'poligono_externo_manzana','localidad_puntual',
                           'ageb_urbana','ageb_rural'] LOOP
    EXECUTE format($q$
      INSERT INTO geo.carga_reparaciones
      SELECT %1$L, id, cvegeo, ST_IsValidReason(geom), ST_Area(geom), NULL
      FROM geo.%1$I WHERE NOT ST_IsValid(geom)$q$, t);

    -- ST_MakeValid puede devolver una colección; para polígonos se conservan solo
    -- las partes poligonales (tipo 3). Los puntos se dejan tal cual.
    IF t <> 'localidad_puntual' THEN
      EXECUTE format($q$
        UPDATE geo.%1$I
        SET geom = ST_Multi(ST_CollectionExtract(ST_MakeValid(geom), 3))
        WHERE NOT ST_IsValid(geom)$q$, t);
      EXECUTE format($q$
        UPDATE geo.carga_reparaciones r SET area_despues = ST_Area(x.geom)
        FROM geo.%1$I x WHERE r.tabla = %1$L AND r.id = x.id$q$, t);
    END IF;

    EXECUTE format('CREATE INDEX IF NOT EXISTS %1$I ON geo.%2$I USING gist (geom)',
                   t || '_geom_gist', t);
    EXECUTE format('ANALYZE geo.%I', t);
  END LOOP;
END $$;

\echo 'Geometrías reparadas por tabla:'
SELECT tabla, count(*) AS reparadas,
       round(sum(area_despues - area_antes)::numeric, 3) AS cambio_area_m2
FROM geo.carga_reparaciones GROUP BY tabla ORDER BY tabla;
