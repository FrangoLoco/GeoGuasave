'use strict';
// Conexión a PostgreSQL con las variables estándar de libpq (PGHOST, PGUSER, PGPASSWORD, PGDATABASE).
const { Pool } = require('pg');
const { construir } = require('./app');

const lprMaxDistM = Number(process.env.LPR_MAX_DIST_M ?? 500);
if (!Number.isFinite(lprMaxDistM) || lprMaxDistM <= 0) {
  console.error(`LPR_MAX_DIST_M debe ser un número positivo de metros; se recibió "${process.env.LPR_MAX_DIST_M}"`);
  process.exit(1);
}
const tamPool = Number(process.env.POOL ?? 10);
const pool = new Pool({ max: tamPool });
const app = construir({ pool, lprMaxDistM });

app.listen({ host: '0.0.0.0', port: Number(process.env.PORT ?? 8000) })
  .then(() => app.log.info({ lprMaxDistM, pool: tamPool }, 'GeoGuasave escuchando'))
  .catch((err) => { app.log.error(err); process.exit(1); });

for (const s of ['SIGTERM', 'SIGINT']) {
  process.on(s, async () => { await app.close(); await pool.end(); process.exit(0); });
}
