#!/usr/bin/env bash
# Prueba preliminar de backend (Fase 4, tarea 1): el mismo script de k6 (50 usuarios
# virtuales, 1 minuto) contra cada prototipo, 3 repeticiones, en la misma máquina.
# Cada corrida arranca el prototipo desde cero y solo él está levantado. El orden
# se alterna por repetición (F-N, N-F, F-N) para no favorecer a ninguno.
# Resúmenes de k6 en bench/resultados/<backend>_r<n>.json; tabla al final.
# Uso, desde la raíz del repositorio: ./bench/correr.sh
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p bench/resultados
[ -s bench/puntos.json ] || ./bench/generar_puntos.sh

docker compose --profile bench build -q bench-fastapi bench-node
docker compose --profile bench stop bench-fastapi bench-node >/dev/null 2>&1 || true

correr() {  # $1 = fastapi | node, $2 = repetición
  local svc="bench-$1"
  docker compose --profile bench up -d --force-recreate --wait "$svc" >/dev/null 2>&1
  # Espera a que el prototipo responda.
  docker compose run --rm -q --entrypoint sh k6 -c \
    "for i in \$(seq 60); do wget -qO- 'http://$svc:8000/reverse?lat=25.5674&lon=-108.4697' >/dev/null 2>&1 && exit 0; sleep 1; done; exit 1"
  echo "== $1, repetición $2"
  # Con el usuario de la máquina, para que k6 pueda escribir en bench/resultados/.
  docker compose run --rm -q --user "$(id -u):$(id -g)" -e BASE_URL="http://$svc:8000" k6 run --quiet \
    --summary-export "/bench/resultados/$1_r$2.json" /bench/k6/reverse.js | grep -E 'http_req_duration|http_reqs|checks_failed|http_req_failed' || true
  docker compose --profile bench stop "$svc" >/dev/null 2>&1
}

correr fastapi 1; correr node 1
correr node 2;    correr fastapi 2
correr fastapi 3; correr node 3

python3 -I - bench/resultados <<'PY'
import json, statistics, sys
from pathlib import Path
d = Path(sys.argv[1])
print(f"\n{'backend':<8} {'rep':>3} {'p95 ms':>8} {'mediana ms':>11} {'sol/s':>9} {'solicitudes':>12} {'fallidas':>9}")
for b in ("fastapi", "node"):
    p95, rps = [], []
    for n in (1, 2, 3):
        m = json.loads((d / f"{b}_r{n}.json").read_text())["metrics"]
        dur, reqs, fail = m["http_req_duration"], m["http_reqs"], m["http_req_failed"]
        p95.append(dur["p(95)"]); rps.append(reqs["rate"])
        print(f"{b:<8} {n:>3} {dur['p(95)']:>8.2f} {dur['med']:>11.2f} {reqs['rate']:>9.1f} {reqs['count']:>12} {fail.get('passes', 0):>9}")
    print(f"{b:<8} {'media':>3} {statistics.mean(p95):>8.2f} {'':>11} {statistics.mean(rps):>9.1f}")
PY
