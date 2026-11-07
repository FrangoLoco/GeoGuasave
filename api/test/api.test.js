'use strict';
// Pruebas de la API contra la base real (Fase 4). Corren dentro del contenedor:
//   docker compose run --rm api npm test
const { test, after } = require('node:test');
const assert = require('node:assert/strict');
const { Writable } = require('node:stream');
const { Pool } = require('pg');
const { construir, ATRIBUCION } = require('../src/app');

const pool = new Pool({ max: 2 });
const registros = [];
const flujo = new Writable({ write(c, e, cb) { registros.push(JSON.parse(c)); cb(); } });
const app = construir({ pool, lprMaxDistM: 500, logger: { stream: flujo } });
after(async () => { await app.close(); await pool.end(); });

const get = (url, headers) => app.inject({ method: 'GET', url, headers });
// Punto en la ciudad de Guasave, el mismo de las pruebas de la Fase 3.
const CIUDAD = '/reverse?lat=25.5674&lon=-108.4697';

test('un punto de la ciudad de Guasave devuelve el contrato completo', async () => {
  const r = await get(CIUDAD);
  assert.equal(r.statusCode, 200);
  assert.match(r.headers['content-type'], /application\/json/);
  const b = r.json();
  assert.deepEqual(Object.keys(b),
    ['municipio', 'fuera_de_guasave', 'sindicatura', 'localidad', 'ageb', 'metodo', 'distancia_m', 'atribucion']);
  assert.deepEqual(b.municipio, { cvegeo: '25011', nombre: 'Guasave' });
  assert.equal(b.fuera_de_guasave, false);
  assert.deepEqual(b.sindicatura, { nombre: 'Alcaldía Central', origen: 'implan' });
  assert.deepEqual(b.localidad, { cvegeo: '250110001', nombre: 'Guasave', ambito: 'U' });
  assert.equal(b.ageb.tipo, 'U');
  assert.match(b.ageb.cvegeo, /^250110001[0-9A-Z]{4}$/);
  assert.equal(b.metodo, 'poligono_localidad');
  assert.equal(b.distancia_m, null);
  assert.equal(b.atribucion, ATRIBUCION);
});

test('la respuesta es igual a la de geo.reverse_geocode más la atribución', async () => {
  const { rows } = await pool.query('SELECT geo.reverse_geocode(-108.4697, 25.5674) AS r');
  assert.deepEqual((await get(CIUDAD)).json(), { ...rows[0].r, atribucion: ATRIBUCION });
});

test('parámetros inválidos responden 422 con mensaje y atribución', async () => {
  for (const q of ['lat=95&lon=-108.5', 'lat=25.5&lon=-181', 'lat=abc&lon=-108.5', 'lon=-108.5', 'lat=25.5', '']) {
    const r = await get(`/reverse?${q}`);
    assert.equal(r.statusCode, 422, q);
    assert.equal(r.json().error, 'parametros_invalidos', q);
    assert.ok(r.json().detalle.length > 0, q);
    assert.equal(r.json().atribucion, ATRIBUCION, q);
  }
});

test('un punto fuera de Sinaloa responde 422', async () => {
  const r = await get('/reverse?lat=19.4326&lon=-99.1332');  // Zócalo, Ciudad de México
  assert.equal(r.statusCode, 422);
  assert.equal(r.json().error, 'fuera_de_sinaloa');
});

test('un punto de otro municipio de Sinaloa responde 200 con fuera_de_guasave', async () => {
  const r = await get('/reverse?lat=24.8091&lon=-107.3940');  // Culiacán
  assert.equal(r.statusCode, 200);
  const b = r.json();
  assert.equal(b.municipio.cvegeo, '25006');
  assert.equal(b.fuera_de_guasave, true);
  for (const k of ['sindicatura', 'localidad', 'ageb', 'metodo', 'distancia_m']) assert.equal(b[k], null, k);
  assert.equal(b.atribucion, ATRIBUCION);
});

test('LPR_MAX_DIST_M se aplica: 300 m de una localidad puntual', async () => {
  // Localidad puntual de Guasave cuyo punto desplazado 300 m al norte queda en Guasave,
  // lejos (> 1 km) de todo polígono y sin otra localidad puntual a 500 m.
  const { rows } = await pool.query(`
    SELECT left(lp.cvegeo, 9) AS cvegeo, ST_Y(t) AS lat, ST_X(t) AS lon
    FROM geo.localidad_puntual lp,
         LATERAL (SELECT ST_Translate(lp.geom, 0, 300) AS g) q,
         LATERAL (SELECT ST_Transform(q.g, 4326) AS t) w
    WHERE lp.cve_mun = '011'
      AND ST_Contains((SELECT geom FROM geo.municipio WHERE cvegeo = '25011'), q.g)
      AND NOT EXISTS (SELECT 1 FROM geo.localidad l WHERE ST_DWithin(l.geom, q.g, 1000))
      AND NOT EXISTS (SELECT 1 FROM geo.poligono_externo p WHERE ST_DWithin(p.geom, q.g, 1000))
      AND NOT EXISTS (SELECT 1 FROM geo.poligono_externo_manzana p WHERE ST_DWithin(p.geom, q.g, 1000))
      AND NOT EXISTS (SELECT 1 FROM geo.localidad_puntual o WHERE o.id <> lp.id AND ST_DWithin(o.geom, q.g, 500))
    ORDER BY lp.cvegeo LIMIT 1`);
  assert.equal(rows.length, 1);
  const { cvegeo, lat, lon } = rows[0];
  const url = `/reverse?lat=${lat}&lon=${lon}`;

  const con500 = (await get(url)).json();
  assert.equal(con500.metodo, 'localidad_puntual');
  assert.equal(con500.localidad.cvegeo, cvegeo);
  assert.ok(Math.abs(con500.distancia_m - 300) < 0.5, String(con500.distancia_m));

  const app250 = construir({ pool, lprMaxDistM: 250, logger: false });
  const con250 = (await app250.inject({ method: 'GET', url })).json();
  await app250.close();
  assert.equal(con250.metodo, 'fuera_de_localidad');
  assert.equal(con250.localidad, null);
  assert.equal(con250.sindicatura.origen, 'voronoi');
});

test('GET /health informa API y base de datos', async () => {
  const r = await get('/health');
  assert.equal(r.statusCode, 200);
  assert.deepEqual(r.json(), { api: 'ok', base_de_datos: 'ok', atribucion: ATRIBUCION });
});

test('CORS abierto', async () => {
  const r = await get(CIUDAD, { origin: 'https://ejemplo.org' });
  assert.equal(r.headers['access-control-allow-origin'], '*');
});

test('documentación OpenAPI con /reverse y /health', async () => {
  const r = await get('/docs/json');
  assert.equal(r.statusCode, 200);
  const doc = r.json();
  assert.match(doc.openapi, /^3\./);
  assert.ok(doc.paths['/reverse'] && doc.paths['/health']);
  assert.equal((await get('/docs')).statusCode < 400, true);
});

test('cada solicitud queda registrada con su latencia', async () => {
  const antes = registros.length;
  await get(CIUDAD);
  const r = registros.slice(antes).find((x) => x.msg === 'solicitud');
  assert.ok(r, 'sin registro de la solicitud');
  assert.equal(r.metodo, 'GET');
  assert.equal(r.url, CIUDAD);
  assert.equal(r.estado, 200);
  assert.equal(typeof r.ms, 'number');
});
