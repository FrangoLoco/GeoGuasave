"""Instrumento 1, paso 2: extrae de las respuestas crudas el municipio y la
localidad que devuelve cada servicio y empareja la localidad con el catálogo
del INEGI (Fase 6a, docs/PLAN.md).

Nombre de localidad que se toma de cada respuesta:
- Google: del primer resultado, el componente `locality`; si no hay,
  `sublocality`. Municipio: el componente `administrative_area_level_2` del
  primer resultado que lo traiga.
- Nominatim: el primero que exista de `hamlet`, `village`, `town` y `city`
  (del más específico al menos). Municipio: `county`.
- GeoGuasave: devuelve la clave del INEGI; no se empareja.

Emparejamiento, con la normalización de etl/emparejar_implan.py (minúsculas,
sin acentos ni puntuación, sin el prefijo "Ejido") contra las localidades de
Guasave en las capas l y lpr:
- Un solo candidato exacto: se acepta.
- Varios candidatos exactos (homónimos): a revisión, una fila por punto, con
  los candidatos ordenados por distancia al punto.
- Ningún candidato exacto: a revisión, una fila por nombre (vale para todos los
  puntos y servicios que lo devuelven), con los 3 candidatos de mayor puntaje.
  El puntaje es el mayor entre el nombre completo y el nombre sin el texto
  entre paréntesis; el desempate es la distancia al punto más cercano.
Las decisiones capturadas en la revisión (cvegeo_elegido y nota) se conservan
al volver a correr el script; "ninguna" deja la localidad sin clave.

La sindicatura de Google y Nominatim es la de su localidad en la tabla del
IMPLAN (data/manual/localidad_sindicatura.csv); si la localidad no está en la
tabla, queda vacía. La de GeoGuasave es la que devuelve.

Entradas: data/eval_raw/, eval/muestra/puntos_control.csv y la base.
Salidas:
  eval/muestra/respuestas.csv              una fila por punto y servicio
  data/manual/revision_respuestas.csv      casos para revisión manual

Uso: python3 eval/muestra/emparejar_respuestas.py   (con la base levantada)
"""
import csv
import io
import json
import math
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "etl"))
from emparejar_implan import candidatos_inegi, normalizar, puntaje  # noqa: E402

PUNTOS = RAIZ / "eval/muestra/puntos_control.csv"
CRUDOS = RAIZ / "data/eval_raw"
TABLA_IMPLAN = RAIZ / "data/manual/localidad_sindicatura.csv"
SALIDA = RAIZ / "eval/muestra/respuestas.csv"
REVISION = RAIZ / "data/manual/revision_respuestas.csv"
CAMPOS_NOMINATIM = ("hamlet", "village", "town", "city")


def sin_parentesis(nombre):
    return normalizar(re.sub(r"\(.*?\)", " ", nombre))


def puntos_6372(puntos):
    """Coordenadas de los puntos en EPSG:6372, para medir distancias en metros."""
    valores = ",".join(f"({int(p['id'])},{float(p['lon'])},{float(p['lat'])})" for p in puntos)
    sql = (f"COPY (SELECT id, ST_X(g), ST_Y(g) FROM (SELECT id, ST_Transform(ST_SetSRID("
           f"ST_MakePoint(lon, lat), 4326), 6372) g FROM (VALUES {valores}) v(id, lon, lat)) t) "
           f"TO STDOUT WITH (FORMAT csv);")
    r = subprocess.run(
        ["docker", "compose", "exec", "-T", "db", "sh", "-c",
         'psql -q -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'],
        input=sql, capture_output=True, text=True, check=True, cwd=RAIZ)
    return {int(i): (float(x), float(y)) for i, x, y in csv.reader(io.StringIO(r.stdout))}


def extraer(servicio, resp):
    """(campo, nombre de localidad, municipio) de una respuesta cruda."""
    if servicio == "google":
        res = resp["results"]
        comps = res[0]["address_components"] if res else []
        mun = next((c["long_name"] for r in res for c in r["address_components"]
                    if "administrative_area_level_2" in c["types"]), "")
        for campo in ("locality", "sublocality"):
            for c in comps:
                if campo in c["types"]:
                    return campo, c["long_name"], mun
        return "", "", mun
    a = resp.get("address", {})
    campo = next((k for k in CAMPOS_NOMINATIM if k in a), "")
    return campo, a.get(campo, ""), a.get("county", "")


def main():
    puntos = list(csv.DictReader(PUNTOS.open(encoding="utf-8")))
    xy = puntos_6372(puntos)
    inegi = candidatos_inegi()
    nombre_inegi, coords = {}, defaultdict(list)
    for c in sorted(inegi, key=lambda c: c["fuente"] != "l"):  # el nombre de l tiene prioridad
        nombre_inegi.setdefault(c["cvegeo"], c["nomgeo"])
        coords[c["cvegeo"]].append((c["x"], c["y"]))
    exactos = defaultdict(set)
    for c in inegi:
        exactos[c["norm"]].add(c["cvegeo"])
    sindicatura = {r["cvegeo"]: r["unidad"] for r in csv.DictReader(TABLA_IMPLAN.open(encoding="utf-8"))}

    def km(cvegeo, ids):
        return round(min(math.dist(xy[i], p) for i in ids for p in coords[cvegeo]) / 1000, 1)

    previas = {}
    if REVISION.exists():
        for d in csv.DictReader(REVISION.open(encoding="utf-8")):
            previas[(d["nombre_norm"], d["punto"])] = (d["cvegeo_elegido"].strip(), d["nota"])

    filas, revision = [], {}  # revision: (nombre_norm, punto) -> datos del caso
    for p in puntos:
        i = int(p["id"])
        g = json.loads((CRUDOS / "geoguasave" / f"{p['id']}.json").read_text())["respuesta"]
        filas.append({"id": i, "servicio": "geoguasave", "campo": "", "nombre_devuelto": (g["localidad"] or {}).get("nombre", ""),
                      "municipio_devuelto": g["municipio"]["nombre"], "localidad_cvegeo": (g["localidad"] or {}).get("cvegeo", ""),
                      "metodo": "clave", "sindicatura": (g["sindicatura"] or {}).get("nombre", "")})
        for servicio in ("google", "nominatim"):
            resp = json.loads((CRUDOS / servicio / f"{p['id']}.json").read_text())["respuesta"]
            campo, nombre, mun = extraer(servicio, resp)
            fila = {"id": i, "servicio": servicio, "campo": campo, "nombre_devuelto": nombre,
                    "municipio_devuelto": mun, "localidad_cvegeo": "", "metodo": "sin_nombre"}
            filas.append(fila)
            if not nombre:
                continue
            n = normalizar(nombre)
            claves = exactos.get(n, set())
            if len(claves) == 1:
                fila.update(localidad_cvegeo=next(iter(claves)), metodo="exacto")
                continue
            clave = (n, str(i) if claves else "")
            caso = revision.setdefault(clave, {"nombre": nombre, "ids": [], "servicios": set(),
                                               "motivo": "homónimo" if claves else "sin coincidencia exacta",
                                               "claves": claves})
            caso["ids"].append(i)
            caso["servicios"].add(servicio)
            fila["_caso"] = clave

    for (n, punto), caso in revision.items():
        ids = caso["ids"]
        if caso["claves"]:
            cands = sorted(caso["claves"], key=lambda c: km(c, ids))
            caso["cands"] = [(c, 100.0) for c in cands]
        else:
            base = sin_parentesis(caso["nombre"])
            mejor = {}
            for c in inegi:
                s = max(puntaje(n, c["norm"]), puntaje(base, sin_parentesis(c["nomgeo"])))
                mejor[c["cvegeo"]] = max(s, mejor.get(c["cvegeo"], 0))
            caso["cands"] = sorted(mejor.items(), key=lambda t: (-t[1], km(t[0], ids)))[:3]
        caso["elegido"], caso["nota"] = previas.get((n, punto), ("", ""))
        e = caso["elegido"]
        if e not in ("", "ninguna") and e not in nombre_inegi:
            raise SystemExit(f"Revisión, {caso['nombre']}: la clave {e} no es una localidad de Guasave")

    for f in filas:
        clave = f.pop("_caso", None)
        if clave:
            e = revision[clave]["elegido"]
            f["metodo"] = {"": "pendiente", "ninguna": "ninguna"}.get(e, "manual")
            f["localidad_cvegeo"] = e if f["metodo"] == "manual" else ""
        if f["servicio"] != "geoguasave":
            f["sindicatura"] = sindicatura.get(f["localidad_cvegeo"], "")

    with SALIDA.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, ["id", "servicio", "campo", "nombre_devuelto", "municipio_devuelto",
                                "localidad_cvegeo", "metodo", "sindicatura"])
        w.writeheader()
        w.writerows(sorted(filas, key=lambda f: (f["id"], f["servicio"])))

    with REVISION.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        cab = ["nombre_devuelto", "nombre_norm", "punto", "servicios", "puntos", "n_puntos", "motivo"]
        for k in (1, 2, 3):
            cab += [f"cand{k}_cvegeo", f"cand{k}_nombre", f"cand{k}_puntaje", f"cand{k}_km"]
        w.writerow(cab + ["cvegeo_elegido", "nota"])
        for (n, punto), c in sorted(revision.items(), key=lambda t: (t[1]["motivo"], -len(t[1]["ids"]), t[0])):
            fila = [c["nombre"], n, punto, "|".join(sorted(c["servicios"])),
                    "|".join(map(str, sorted(c["ids"]))), len(c["ids"]), c["motivo"]]
            for cv, s in c["cands"][:3]:
                fila += [cv, nombre_inegi[cv], s, km(cv, c["ids"])]
            fila += [""] * (7 + 4 * 3 - len(fila))
            w.writerow(fila + [c["elegido"], c["nota"]])

    print(f"{'servicio':<12}" + "".join(f"{m:>12}" for m in ("clave", "exacto", "manual", "ninguna", "pendiente", "sin_nombre")))
    for s in ("geoguasave", "google", "nominatim"):
        k = Counter(f["metodo"] for f in filas if f["servicio"] == s)
        print(f"{s:<12}" + "".join(f"{k[m]:>12}" for m in ("clave", "exacto", "manual", "ninguna", "pendiente", "sin_nombre")))
    k = Counter(c["motivo"] for c in revision.values())
    sin = sum(1 for c in revision.values() if not c["elegido"])
    print(f"Revisión: {len(revision)} casos ({dict(k)}), {sin} sin decisión")
    print(f"Escritos {SALIDA.relative_to(RAIZ)} y {REVISION.relative_to(RAIZ)}")


if __name__ == "__main__":
    main()
