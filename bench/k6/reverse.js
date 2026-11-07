// Prueba preliminar de backend (Fase 4, tarea 1): 50 usuarios virtuales durante 1 minuto.
// Cada iteración consulta el siguiente punto de bench/puntos.json (en orden y cíclico),
// así ambos prototipos reciben la misma secuencia de puntos.
import http from 'k6/http';
import { check } from 'k6';
import exec from 'k6/execution';
import { SharedArray } from 'k6/data';

const puntos = new SharedArray('puntos', () => JSON.parse(open('/bench/puntos.json')));
const BASE = __ENV.BASE_URL;

export const options = {
  vus: 50,
  duration: '1m',
  summaryTrendStats: ['avg', 'min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
};

export default function () {
  const [lat, lon] = puntos[exec.scenario.iterationInTest % puntos.length];
  const r = http.get(`${BASE}/reverse?lat=${lat}&lon=${lon}`);
  check(r, { 'status 200': (x) => x.status === 200 });
}
