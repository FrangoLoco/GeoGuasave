// Prototipo Node.js (Fastify) de GET /reverse para la prueba preliminar de backend (Fase 4, tarea 1).
const Fastify = require('fastify');
const { Pool } = require('pg');

const POOL = Number(process.env.POOL || 10);
const pool = new Pool({
  host: 'db', user: process.env.POSTGRES_USER, password: process.env.POSTGRES_PASSWORD,
  database: process.env.POSTGRES_DB, min: POOL, max: POOL,
});

const app = Fastify({ logger: false });
// Errores de validación con 422, como FastAPI.
app.setErrorHandler((err, req, reply) => {
  reply.code(err.validation ? 422 : 500).send({ detalle: err.message });
});

app.get('/reverse', {
  schema: {
    querystring: {
      type: 'object',
      required: ['lat', 'lon'],
      properties: {
        lat: { type: 'number', minimum: -90, maximum: 90 },
        lon: { type: 'number', minimum: -180, maximum: 180 },
      },
    },
  },
}, async (req, reply) => {
  const { rows } = await pool.query('SELECT geo.reverse_geocode($1, $2)::text AS r', [req.query.lon, req.query.lat]);
  if (rows[0].r === null) return reply.code(422).send({ detalle: 'punto fuera de Sinaloa' });
  return reply.type('application/json').send(rows[0].r);
});

app.listen({ host: '0.0.0.0', port: 8000 });
