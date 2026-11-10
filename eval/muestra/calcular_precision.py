"""Instrumento 1, paso 3: tasas de acierto por nivel, McNemar exacta pareada e
intervalo de confianza de la diferencia pareada (Fase 6a, docs/PLAN.md).

Acierto por nivel (docs/decisiones.md):
- Municipio: el nombre devuelto, normalizado, es "guasave". Los puntos donde
  Google devuelve el municipio Juan José Ríos se reportan aparte y salen de
  este nivel para los tres servicios (n = 363).
- Sindicatura: la sindicatura del servicio es la de referencia, o una de ellas
  en los traslapes del IMPLAN. Sin referencia (sin cobertura del IMPLAN) no se
  evalúa.
- Localidad: la clave del INEGI del servicio es la de referencia. Sin
  localidad de referencia no se evalúa.

Grupos: todos los puntos, cada estrato y el ámbito de la localidad de
referencia (U, R o sin localidad).

Estadística (solo biblioteca estándar):
- Tasa con intervalo de Wilson al 95 %.
- McNemar exacta: binomial bilateral sobre los pares discordantes.
- Diferencia pareada (GeoGuasave menos el otro) con el intervalo de Newcombe
  (1998, Stat. Med. 17:2635-2650, método 10): intervalos de Wilson de cada
  proporción combinados con phi, cuyo numerador se corrige a
  max(ad - bc - n/2, 0) cuando ad > bc.
- Con --margen M (proporción, por ejemplo 0.05) se reporta si el límite
  inferior de la diferencia frente a Google es mayor que -M (no inferioridad,
  H1). El margen lo define el usuario con su asesor.

Salidas en eval/resultados/: precision_tasas.csv, precision_mcnemar.csv y
precision_juan_jose_rios.csv.

Uso: python3 eval/muestra/calcular_precision.py [--margen 0.05]
"""
import argparse
import csv
import math
import sys
from collections import defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "etl"))
from emparejar_implan import normalizar  # noqa: E402

PUNTOS = RAIZ / "eval/muestra/puntos_control.csv"
RESPUESTAS = RAIZ / "eval/muestra/respuestas.csv"
SALIDA = RAIZ / "eval/resultados"
SERVICIOS = ("geoguasave", "google", "nominatim")
NIVELES = ("municipio", "sindicatura", "localidad")
Z = 1.959963984540054


def wilson(x, n):
    if n == 0:
        return (float("nan"),) * 2
    p = x / n
    centro = (p + Z * Z / (2 * n)) / (1 + Z * Z / n)
    radio = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / (1 + Z * Z / n)
    return centro - radio, centro + radio


def mcnemar_exacta(b, c):
    m = b + c
    if m == 0:
        return 1.0
    cola = sum(math.comb(m, k) for k in range(min(b, c) + 1)) / 2 ** m
    return min(1.0, 2 * cola)


def newcombe(a, b, c, d):
    """IC 95 % de p1 - p2 en una tabla pareada: a = ambos aciertan,
    b = solo el 1, c = solo el 2, d = ninguno (Newcombe 1998, método 10;
    en su notación e, f, g, h)."""
    n = a + b + c + d
    p1, p2 = (a + b) / n, (a + c) / n
    l1, u1 = wilson(a + b, n)
    l2, u2 = wilson(a + c, n)
    den = (a + b) * (c + d) * (a + c) * (b + d)
    num = a * d - b * c
    if num > 0:
        num = max(num - n / 2, 0)
    phi = num / math.sqrt(den) if den else 0.0
    dif = p1 - p2
    inf = dif - math.sqrt(max(0.0, (p1 - l1) ** 2 - 2 * phi * (p1 - l1) * (u2 - p2) + (u2 - p2) ** 2))
    sup = dif + math.sqrt(max(0.0, (u1 - p1) ** 2 - 2 * phi * (u1 - p1) * (p2 - l2) + (p2 - l2) ** 2))
    return dif, inf, sup


def aciertos(puntos, respuestas):
    """{(nivel, id): {servicio: bool}} solo para los puntos evaluables en ese nivel."""
    jjr = {i for i, r in respuestas["google"].items() if r["municipio_devuelto"] == "Juan José Ríos"}
    res = {}
    for p in puntos:
        i = p["id"]
        if i not in jjr:
            res[("municipio", i)] = {s: normalizar(respuestas[s][i]["municipio_devuelto"]) == "guasave" for s in SERVICIOS}
        if p["sindicatura"]:
            ref = set(p["sindicatura"].split("|"))
            res[("sindicatura", i)] = {s: respuestas[s][i]["sindicatura"] in ref for s in SERVICIOS}
        if p["localidad_cvegeo"]:
            res[("localidad", i)] = {s: respuestas[s][i]["localidad_cvegeo"] == p["localidad_cvegeo"] for s in SERVICIOS}
    return res, jjr


def demo():
    # Newcombe (1998), tabla III, método 10: (e, f, g, h) -> (L, U).
    for celdas, esperado in (((36, 12, 2, 0), (0.0569, 0.3404)), ((20, 12, 2, 16), (0.0562, 0.3292)),
                             ((18, 12, 2, 18), (0.0562, 0.3290)), ((35, 14, 0, 1), (0.1461, 0.4175)),
                             ((1, 98, 0, 1), (0.9171, 0.9916)), ((53, 0, 0, 1), (-0.0729, 0.0729))):
        _, inf, sup = newcombe(*celdas)
        assert (round(inf, 4), round(sup, 4)) == esperado, (celdas, inf, sup)
    assert mcnemar_exacta(9, 2) == 2 * (1 + 11 + 55) / 2 ** 11  # 2 P(X <= 2), X ~ Bin(11, 1/2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--margen", type=float, help="margen de no inferioridad para H1, como proporción")
    args = ap.parse_args()
    demo()

    puntos = list(csv.DictReader(PUNTOS.open(encoding="utf-8")))
    respuestas = defaultdict(dict)
    for r in csv.DictReader(RESPUESTAS.open(encoding="utf-8")):
        respuestas[r["servicio"]][r["id"]] = r
    res, jjr = aciertos(puntos, respuestas)
    por_id = {p["id"]: p for p in puntos}
    grupos = {"todos": lambda p: True}
    for e in ("numero_exterior", "rural", "limite"):
        grupos[f"estrato={e}"] = lambda p, e=e: p["estrato"] == e
    for a, nom in (("U", "U"), ("R", "R"), ("", "sin_localidad")):
        grupos[f"ambito={nom}"] = lambda p, a=a: p["localidad_ambito"] == a

    SALIDA.mkdir(parents=True, exist_ok=True)
    tasas, pruebas = [], []
    for nivel in NIVELES:
        for grupo, f in grupos.items():
            filas = [v for (nv, i), v in res.items() if nv == nivel and f(por_id[i])]
            n = len(filas)
            if n == 0:
                continue
            for s in SERVICIOS:
                x = sum(v[s] for v in filas)
                lo, hi = wilson(x, n)
                tasas.append({"nivel": nivel, "grupo": grupo, "servicio": s, "n": n, "aciertos": x,
                              "tasa": round(x / n, 4), "ic95_inf": round(lo, 4), "ic95_sup": round(hi, 4)})
            for otro in ("google", "nominatim"):
                a = sum(v["geoguasave"] and v[otro] for v in filas)
                b = sum(v["geoguasave"] and not v[otro] for v in filas)
                c = sum(not v["geoguasave"] and v[otro] for v in filas)
                d = n - a - b - c
                dif, inf, sup = newcombe(a, b, c, d)
                fila = {"nivel": nivel, "grupo": grupo, "comparacion": f"geoguasave-{otro}", "n": n,
                        "ambos": a, "solo_geoguasave": b, "solo_otro": c, "ninguno": d,
                        "p_mcnemar_exacta": float(f"{mcnemar_exacta(b, c):.3g}"),
                        "diferencia": round(dif, 4), "ic95_inf": round(inf, 4), "ic95_sup": round(sup, 4),
                        "no_inferior": ""}
                if args.margen is not None and otro == "google":
                    fila["no_inferior"] = "sí" if inf > -args.margen else "no"
                pruebas.append(fila)

    for nombre, filas in (("precision_tasas.csv", tasas), ("precision_mcnemar.csv", pruebas)):
        with (SALIDA / nombre).open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, list(filas[0]))
            w.writeheader()
            w.writerows(filas)
    with (SALIDA / "precision_juan_jose_rios.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "estrato", "sindicatura_referencia"] + [f"municipio_{s}" for s in SERVICIOS])
        for i in sorted(jjr, key=int):
            p = por_id[i]
            w.writerow([i, p["estrato"], p["sindicatura"]] + [respuestas[s][i]["municipio_devuelto"] for s in SERVICIOS])

    print(f"{'nivel':<12}{'grupo':<24}{'n':>4}" + "".join(f"{s:>22}" for s in SERVICIOS))
    for k in range(0, len(tasas), 3):
        t = tasas[k:k + 3]
        print(f"{t[0]['nivel']:<12}{t[0]['grupo']:<24}{t[0]['n']:>4}"
              + "".join(f"{x['tasa']:>8.1%} ({x['ic95_inf']:.1%}-{x['ic95_sup']:.1%})".rjust(22) for x in t))
    print()
    print(f"{'nivel':<12}{'grupo':<24}{'comparación':<22}{'b':>4}{'c':>4}{'p exacta':>10}{'dif':>8}  IC 95 %")
    for x in pruebas:
        print(f"{x['nivel']:<12}{x['grupo']:<24}{x['comparacion']:<22}{x['solo_geoguasave']:>4}{x['solo_otro']:>4}"
              f"{x["p_mcnemar_exacta"]:>10.2g}{x['diferencia']:>8.1%}  ({x['ic95_inf']:.1%}, {x['ic95_sup']:.1%})"
              + (f"  no inferior: {x['no_inferior']}" if x["no_inferior"] else ""))
    print(f"\nJuan José Ríos (aparte del nivel municipio): {len(jjr)} puntos")
    print(f"Escritos en {SALIDA.relative_to(RAIZ)}/")


if __name__ == "__main__":
    main()
