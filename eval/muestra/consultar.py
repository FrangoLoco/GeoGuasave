"""Instrumento 1, paso 1: consulta los 400 puntos de control en GeoGuasave,
la Geocoding API de Google y Nominatim (Fase 6a, docs/PLAN.md).

Cada respuesta cruda se guarda en data/eval_raw/<servicio>/<id>.json junto con
la fecha de consulta y la URL (sin la clave de Google). Si el archivo ya
existe, el punto no se vuelve a consultar. Las respuestas con error (HTTP o un
status de Google distinto de OK y ZERO_RESULTS) no se guardan y detienen el
script, para que una corrida nueva las reintente.

- GeoGuasave: la API local, GET /reverse (API_PORT de .env).
- Google: geocodificación inversa, language=es, clave GOOGLE_MAPS_API_KEY de .env.
- Nominatim: /reverse con format=jsonv2, accept-language=es, una solicitud
  cada 1.1 s y un User-Agent que identifica la aplicación.

Uso, desde la raíz y con la API levantada:
  python3 eval/muestra/consultar.py --prueba   # GeoGuasave y Nominatim, sin Google
  python3 eval/muestra/consultar.py            # los tres servicios
"""
import csv
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
PUNTOS = RAIZ / "eval/muestra/puntos_control.csv"
CRUDOS = RAIZ / "data/eval_raw"
USER_AGENT = "GeoGuasave/1.0 (evaluacion de tesis; +https://github.com/FrangoLoco/GeoGuasave)"
PAUSA_NOMINATIM_S = 1.1


def leer_env():
    env = {}
    ruta = RAIZ / ".env"
    if ruta.exists():
        for linea in ruta.read_text().splitlines():
            if "=" in linea and not linea.lstrip().startswith("#"):
                k, v = linea.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def pedir(url, intentos=4):
    """GET de JSON. Reintenta fallas de red, timeouts y HTTP 429/5xx con espera
    creciente (10, 20, 40 s); cualquier otro error HTTP sube de inmediato."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for n in range(intentos):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code != 429 and e.code < 500 or n == intentos - 1:
                raise
            motivo = f"HTTP {e.code}"
        except (urllib.error.URLError, TimeoutError) as e:
            if n == intentos - 1:
                raise
            motivo = repr(e)
        espera = 10 * 2 ** n
        print(f"  {motivo}; reintento en {espera} s", file=sys.stderr)
        time.sleep(espera)


def url_geoguasave(p, env):
    q = urllib.parse.urlencode({"lat": p["lat"], "lon": p["lon"]})
    return f"http://127.0.0.1:{env.get('API_PORT', '8000')}/reverse?{q}"


def url_google(p, env):
    q = urllib.parse.urlencode({"latlng": f"{p['lat']},{p['lon']}", "language": "es"})
    return f"https://maps.googleapis.com/maps/api/geocode/json?{q}"


def url_nominatim(p, env):
    q = urllib.parse.urlencode({"format": "jsonv2", "lat": p["lat"], "lon": p["lon"],
                                "addressdetails": 1, "accept-language": "es"})
    return f"https://nominatim.openstreetmap.org/reverse?{q}"


def consultar(servicio, hacer_url, puntos, env, pausa=0.0):
    carpeta = CRUDOS / servicio
    carpeta.mkdir(parents=True, exist_ok=True)
    nuevos = 0
    for p in puntos:
        destino = carpeta / f"{p['id']}.json"
        if destino.exists():
            continue
        url = hacer_url(p, env)
        url_real = url
        if servicio == "google":
            url_real += "&key=" + urllib.parse.quote(env["GOOGLE_MAPS_API_KEY"])
        try:
            respuesta = pedir(url_real)
        except urllib.error.HTTPError as e:
            # GeoGuasave responde 422 fuera de Sinaloa; ningún punto debería estar ahí.
            sys.exit(f"{servicio}, punto {p['id']}: HTTP {e.code} {e.read()[:200]!r}")
        if servicio == "google" and respuesta.get("status") not in ("OK", "ZERO_RESULTS"):
            sys.exit(f"google, punto {p['id']}: {respuesta.get('status')} {respuesta.get('error_message', '')}")
        registro = {"id": p["id"], "lat": p["lat"], "lon": p["lon"], "url": url,
                    "consultado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "respuesta": respuesta}
        destino.write_text(json.dumps(registro, ensure_ascii=False, indent=1))
        nuevos += 1
        if pausa:
            time.sleep(pausa)
    print(f"{servicio}: {nuevos} consultas nuevas, {len(list(carpeta.glob('*.json')))} guardadas")


def main():
    prueba = "--prueba" in sys.argv[1:]
    env = leer_env()
    with PUNTOS.open(newline="") as f:
        puntos = list(csv.DictReader(f))
    if not prueba and not env.get("GOOGLE_MAPS_API_KEY"):
        sys.exit("Falta GOOGLE_MAPS_API_KEY en .env (o usa --prueba).")
    consultar("geoguasave", url_geoguasave, puntos, env)
    consultar("nominatim", url_nominatim, puntos, env, PAUSA_NOMINATIM_S)
    if prueba:
        print("google: omitido (modo de prueba)")
    else:
        consultar("google", url_google, puntos, env)


if __name__ == "__main__":
    main()
