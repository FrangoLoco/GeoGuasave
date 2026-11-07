'use strict';
// API de GeoGuasave (Fase 4). La lógica de geocodificación vive en geo.reverse_geocode;
// aquí solo se validan los parámetros, se agrega la atribución y se documenta el contrato.
const Fastify = require('fastify');
const { LogController } = Fastify;

const ATRIBUCION = 'Fuente: INEGI, Marco Geoestadístico 2022; IMPLAN Guasave, Cartografía de sindicaturas.';

const clave = (props) => ({ type: 'object', nullable: true, properties: props });
const RESPUESTA = {
  type: 'object',
  properties: {
    municipio: clave({ cvegeo: { type: 'string' }, nombre: { type: 'string' } }),
    fuera_de_guasave: { type: 'boolean' },
    sindicatura: clave({ nombre: { type: 'string' }, origen: { type: 'string', enum: ['implan', 'voronoi'] } }),
    localidad: clave({ cvegeo: { type: 'string' }, nombre: { type: 'string' }, ambito: { type: 'string', enum: ['U', 'R'] } }),
    ageb: clave({ cvegeo: { type: 'string' }, tipo: { type: 'string', enum: ['U', 'R'] } }),
    metodo: {
      type: 'string', nullable: true,
      enum: ['poligono_localidad', 'poligono_externo', 'localidad_puntual', 'fuera_de_localidad', null],
    },
    distancia_m: { type: 'number', nullable: true, description: 'Solo con metodo = localidad_puntual' },
    atribucion: { type: 'string' },
  },
};
const ERROR = {
  type: 'object',
  properties: { error: { type: 'string' }, detalle: { type: 'string' }, atribucion: { type: 'string' } },
};

function construir({ pool, lprMaxDistM, logger = true }) {
  // Un registro por solicitud (en onResponse), con su latencia; no los dos de Fastify.
  const app = Fastify({ logger, logController: new LogController({ disableRequestLogging: true }) });

  app.register(require('@fastify/cors'), { origin: '*' });  // API abierta
  app.register(require('@fastify/swagger'), {
    openapi: {
      info: {
        title: 'GeoGuasave',
        version: '1.0.0',
        description: 'Geocodificación inversa para el municipio de Guasave, Sinaloa. ' + ATRIBUCION,
      },
    },
  });
  app.register(require('@fastify/swagger-ui'), { routePrefix: '/docs' });

  app.addHook('onResponse', (req, reply, done) => {
    req.log.info({ metodo: req.method, url: req.url, estado: reply.statusCode,
                   ms: Math.round(reply.elapsedTime * 100) / 100 }, 'solicitud');
    done();
  });

  app.setErrorHandler((err, req, reply) => {
    if (err.validation) {
      return reply.code(422).send({ error: 'parametros_invalidos', detalle: err.message, atribucion: ATRIBUCION });
    }
    req.log.error(err);
    return reply.code(500).send({ error: 'error_interno', detalle: 'Error interno del servidor', atribucion: ATRIBUCION });
  });
  app.setNotFoundHandler((req, reply) => {
    reply.code(404).send({ error: 'no_encontrado', detalle: `No existe ${req.method} ${req.url}`, atribucion: ATRIBUCION });
  });

  // Las rutas van en un plugin registrado después de @fastify/swagger, para que entren en OpenAPI.
  app.register(async (app) => {
    app.get('/reverse', {
      schema: {
        summary: 'Municipio, sindicatura, localidad y AGEB de un punto',
        querystring: {
          type: 'object',
          required: ['lat', 'lon'],
          properties: {
            lat: { type: 'number', minimum: -90, maximum: 90, description: 'Latitud (EPSG:4326)' },
            lon: { type: 'number', minimum: -180, maximum: 180, description: 'Longitud (EPSG:4326)' },
          },
        },
        response: { 200: RESPUESTA, 422: ERROR },
      },
    }, async (req, reply) => {
      const { rows } = await pool.query('SELECT geo.reverse_geocode($1, $2, $3) AS r',
                                        [req.query.lon, req.query.lat, lprMaxDistM]);
      if (rows[0].r === null) {
        return reply.code(422).send({
          error: 'fuera_de_sinaloa',
          detalle: 'El punto está fuera de Sinaloa; GeoGuasave solo cubre el estado (y detalla Guasave).',
          atribucion: ATRIBUCION,
        });
      }
      return { ...rows[0].r, atribucion: ATRIBUCION };
    });

    app.get('/health', {
      schema: {
        summary: 'Estado de la API y de la base de datos',
        response: {
          200: { type: 'object', properties: { api: { type: 'string' }, base_de_datos: { type: 'string' }, atribucion: { type: 'string' } } },
          503: { type: 'object', properties: { api: { type: 'string' }, base_de_datos: { type: 'string' }, atribucion: { type: 'string' } } },
        },
      },
    }, async (req, reply) => {
      try {
        // La base responde y tiene cargados la función y los polígonos de sindicatura.
        const { rows } = await pool.query(
          "SELECT to_regprocedure('geo.reverse_geocode(double precision, double precision, double precision)') IS NOT NULL " +
          "AND to_regclass('geo.sindicatura_poligono') IS NOT NULL AS ok");
        if (!rows[0].ok) {
          return reply.code(503).send({ api: 'ok', base_de_datos: 'sin_datos', atribucion: ATRIBUCION });
        }
        return { api: 'ok', base_de_datos: 'ok', atribucion: ATRIBUCION };
      } catch (err) {
        req.log.error(err);
        return reply.code(503).send({ api: 'ok', base_de_datos: 'error', atribucion: ATRIBUCION });
      }
    });
  });

  return app;
}

module.exports = { construir, ATRIBUCION };
