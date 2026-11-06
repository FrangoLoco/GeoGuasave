"""Empareja las localidades del IMPLAN con las claves del INEGI (Fase 2, paso 2).

Orden (docs/PLAN.md):
  1. Coincidencia exacta del nombre normalizado en la capa l de Guasave.
  2. Coincidencia exacta en lpr de Guasave.
  3. Coincidencia aproximada (difflib) contra l + lpr; va a revisión manual.
Si un nombre tiene más de un candidato exacto, o una misma clave del INEGI queda
asignada a más de una fila del IMPLAN, el caso va a revisión.

La normalización (minúsculas, sin acentos ni puntuación, sin el prefijo
"Ejido") solo se usa para comparar; los CSV guardan los nombres originales.

Entradas: data/manual/implan_localidades.csv y la base (geo.localidad,
geo.localidad_puntual). Salidas:
  data/manual/localidad_sindicatura.csv     emparejamientos resueltos
  data/manual/revision_emparejamiento.csv   casos para revisión manual

Uso: python3 etl/emparejar_implan.py   (con la base levantada)
"""
import csv
import io
import math
import re
import subprocess
import unicodedata
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
IMPLAN = RAIZ / "data/manual/implan_localidades.csv"
SALIDA = RAIZ / "data/manual/localidad_sindicatura.csv"
REVISION = RAIZ / "data/manual/revision_emparejamiento.csv"

UMBRAL = 80  # puntaje mínimo (0-100) para proponer una coincidencia aproximada
PREFIJOS = ("ejido ",)

SQL = """
COPY (
  SELECT cvegeo, nomgeo, 'l' AS fuente,
         ST_X(ST_PointOnSurface(geom)) AS x, ST_Y(ST_PointOnSurface(geom)) AS y
  FROM geo.localidad WHERE cve_mun = '011'
  UNION ALL
  SELECT left(cvegeo, 9), nomgeo, 'lpr', ST_X(geom), ST_Y(geom)
  FROM geo.localidad_puntual WHERE cve_mun = '011'
) TO STDOUT WITH (FORMAT csv, HEADER);
"""


def normalizar(nombre):
    s = unicodedata.normalize("NFKD", nombre.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    for p in PREFIJOS:
        if s.startswith(p):
            s = s[len(p):]
    return s


def puntaje(a, b):
    return round(100 * SequenceMatcher(None, a, b).ratio(), 1)


def candidatos_inegi():
    r = subprocess.run(
        ["docker", "compose", "exec", "-T", "db", "sh", "-c",
         'psql -q -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'],
        input=SQL, capture_output=True, text=True, check=True, cwd=RAIZ)
    filas = list(csv.DictReader(io.StringIO(r.stdout)))
    for f in filas:
        f["norm"] = normalizar(f["nomgeo"])
        f["x"], f["y"] = float(f["x"]), float(f["y"])
    return filas


def main():
    implan = list(csv.DictReader(IMPLAN.open(encoding="utf-8")))
    inegi = candidatos_inegi()
    por_nombre = {"l": defaultdict(list), "lpr": defaultdict(list)}
    for c in inegi:
        por_nombre[c["fuente"]][c["norm"]].append(c)

    resultados = []  # una entrada por fila del IMPLAN
    for row in implan:
        n = normalizar(row["localidad"])
        res = {"row": row, "cands": [], "metodo": None, "motivo": ""}
        for fuente in ("l", "lpr"):
            exactos = por_nombre[fuente].get(n, [])
            if len(exactos) == 1:
                res.update(metodo="exacto", cands=[(exactos[0], 100.0)], fuente=fuente)
                break
            if len(exactos) > 1:
                res.update(motivo=f"{len(exactos)} candidatos exactos en {fuente}",
                           cands=[(c, 100.0) for c in exactos])
                break
        else:
            todos = sorted(((c, puntaje(n, c["norm"])) for c in inegi), key=lambda t: -t[1])
            vistos, top = set(), []
            for c, p in todos:  # sin repetir clave (l y lpr comparten las rurales)
                if c["cvegeo"] not in vistos:
                    vistos.add(c["cvegeo"])
                    top.append((c, p))
                if len(top) == 3:
                    break
            res["cands"] = top
            res["motivo"] = "aproximado" if top[0][1] >= UMBRAL else "sin coincidencia"
        resultados.append(res)

    # Una clave del INEGI asignada por coincidencia exacta a dos o más filas del IMPLAN.
    usos = Counter(r["cands"][0][0]["cvegeo"] for r in resultados if r["metodo"] == "exacto")
    for r in resultados:
        if r["metodo"] == "exacto" and usos[r["cands"][0][0]["cvegeo"]] > 1:
            r["metodo"] = None
            r["motivo"] = f"clave asignada a {usos[r['cands'][0][0]['cvegeo']]} filas del IMPLAN"

    # Para ayudar en la revisión: distancia de cada candidato a la cabecera de la unidad.
    cabecera = {}
    for r in resultados:
        if r["metodo"] == "exacto" and r["row"]["rango"] != "Comunidad" and r["row"]["num_implan"] == "1":
            c = r["cands"][0][0]
            cabecera[r["row"]["unidad"]] = (c["x"], c["y"])

    def dist_km(r, c):
        cab = cabecera.get(r["row"]["unidad"])
        return round(math.dist(cab, (c["x"], c["y"])) / 1000, 1) if cab else ""

    with SALIDA.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["cvegeo", "nombre_inegi", "nombre_implan", "unidad", "metodo_match", "puntaje"])
        for r in resultados:
            if r["metodo"] == "exacto":
                c, p = r["cands"][0]
                w.writerow([c["cvegeo"], c["nomgeo"], r["row"]["localidad"], r["row"]["unidad"], "exacto", p])

    with REVISION.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        cab = ["unidad", "num_implan", "nombre_implan", "rango", "poblacion", "motivo"]
        for i in (1, 2, 3):
            cab += [f"cand{i}_cvegeo", f"cand{i}_nombre", f"cand{i}_puntaje", f"cand{i}_km_cabecera"]
        w.writerow(cab + ["cvegeo_elegido", "nota"])
        for r in resultados:
            if r["metodo"]:
                continue
            row = r["row"]
            fila = [row["unidad"], row["num_implan"], row["localidad"], row["rango"], row["poblacion"], r["motivo"]]
            # Los candidatos exactos múltiples pueden ser más de 3; se listan los 3 más cercanos a la cabecera.
            cands = sorted(r["cands"], key=lambda t: (-t[1], dist_km(r, t[0]) if cabecera.get(row["unidad"]) else 0))
            for c, p in cands[:3]:
                fila += [c["cvegeo"], c["nomgeo"], p, dist_km(r, c)]
            fila += [""] * (6 + 4 * 3 - len(fila))
            w.writerow(fila + ["", ""])

    # Resumen
    print(f"{'unidad':<24}{'filas':>6}{'exacto l':>9}{'exacto lpr':>11}{'aprox':>7}{'sin coinc':>10}{'ambiguo':>9}")
    tot = Counter()
    for unidad in dict.fromkeys(r["row"]["unidad"] for r in resultados):
        rs = [r for r in resultados if r["row"]["unidad"] == unidad]
        k = Counter()
        for r in rs:
            if r["metodo"] == "exacto":
                k["exacto " + r["fuente"]] += 1
            elif r["motivo"] == "aproximado":
                k["aprox"] += 1
            elif r["motivo"] == "sin coincidencia":
                k["sin"] += 1
            else:
                k["ambiguo"] += 1
        tot += k
        print(f"{unidad:<24}{len(rs):>6}{k['exacto l']:>9}{k['exacto lpr']:>11}{k['aprox']:>7}{k['sin']:>10}{k['ambiguo']:>9}")
    print(f"{'TOTAL':<24}{len(resultados):>6}{tot['exacto l']:>9}{tot['exacto lpr']:>11}{tot['aprox']:>7}{tot['sin']:>10}{tot['ambiguo']:>9}")
    print(f"Escritos {SALIDA.relative_to(RAIZ)} y {REVISION.relative_to(RAIZ)}")


if __name__ == "__main__":
    main()
