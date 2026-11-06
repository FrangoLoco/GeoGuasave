"""Transcribe las tablas del IMPLAN a data/manual/implan_localidades.csv.

Fuente: data/manual/implan/implan/*.txt, que son la salida de `pdftotext -layout`
de los PDF del IMPLAN (son PDF de texto generados con Word, no imágenes).

Por cada unidad compara la suma de habitantes con el total impreso al final de
la tabla y reporta saltos en la numeración y líneas que no se pudieron leer.
Sale con código 1 si algo no cuadra.

Uso: python3 etl/transcribir_implan.py
"""
import csv
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ORIGEN = RAIZ / "data/manual/implan/implan"
SALIDA = RAIZ / "data/manual/implan_localidades.csv"

RANGOS = "Alcaldía Central|Sindicatura|Comisaría|Comunidad"
FILA = re.compile(rf"^\s*(\d+)\s+(.+?)\s{{2,}}({RANGOS})\s+(.+?)\s{{2,}}([\d,]+)\s*$")
# Fila cuyo rango quedó partido en otras líneas (se completa con CORRECCIONES).
FILA_SIN_RANGO = re.compile(r"^\s*(\d+)\s+(.+?)\s{2,}((?:CATASTRAL|IMAGEN).*?)\s{2,}([\d,]+)\s*$")
TOTAL = re.compile(r"^\s*([\d,]+)\s*$")
# Líneas de encabezado que no son datos (en La Trinidad "NÚMERO DE" viene partido).
ENCABEZADO = re.compile(r"LOCALIDAD|NÚMER|^\s*O DE\s*$|HABITANTES|^\s*(SINDICATURA|ALCALDÍA)")

# Celdas que en el PDF ocupan dos líneas. Se verificaron contra el PDF con
# `pdftotext -raw`. Clave: (unidad, número de fila del IMPLAN).
CORRECCIONES = {
    ("Benito Juárez", 1): {"localidad": "Gabriel Leyva Solano (Benito Juárez)",
                           "rango": "Sindicatura y Comisaría"},
    ("San Rafael", 1): {"localidad": "San Rafael (General Miguel Valle Dávalos)"},
}
# Fragmentos de esas celdas partidas; se ignoran porque CORRECCIONES ya los incluye.
FRAGMENTOS = {"Sindicatura y", "Comisaría", "San Rafael (General Miguel Valle", "Dávalos)"}


def nombre_unidad(titulo):
    t = re.sub(r"^SINDICATURA DE\s+", "", titulo.strip())
    # Title case en español: artículos y preposiciones en minúscula salvo al inicio.
    palabras = [p.lower() if p.lower() in {"de", "la", "el", "los", "las"} and i else p.capitalize()
                for i, p in enumerate(t.split())]
    return " ".join(palabras)


def leer(ruta):
    lineas = ruta.read_text(encoding="utf-8").replace("\f", "\n").splitlines()
    titulo = next(l for l in lineas if l.strip())
    unidad = nombre_unidad(titulo)
    filas, totales, raras = [], [], []
    for l in lineas[1:]:
        if not l.strip() or ENCABEZADO.search(l) or l.strip() in FRAGMENTOS:
            continue
        if m := FILA.match(l):
            num, loc, rango, _plano, pob = m.groups()
        elif m := FILA_SIN_RANGO.match(l):
            (num, loc, _plano, pob), rango = m.groups(), ""
        else:
            m = None
        if m:
            fila = {"num_implan": int(num), "unidad": unidad, "localidad": loc.strip(),
                    "rango": rango, "poblacion": int(pob.replace(",", ""))}
            fila.update(CORRECCIONES.get((unidad, fila["num_implan"]), {}))
            if not fila["localidad"] or not fila["rango"]:
                raras.append(l)
            filas.append(fila)
        elif m := TOTAL.match(l):
            totales.append(int(m.group(1).replace(",", "")))
        else:
            raras.append(l)
    return unidad, filas, totales, raras


def main():
    todas, ok = [], True
    print(f"{'unidad':<26}{'filas':>6}{'suma':>9}{'total':>9}  observaciones")
    for ruta in sorted(ORIGEN.glob("*.txt")):
        unidad, filas, totales, raras = leer(ruta)
        suma = sum(f["poblacion"] for f in filas)
        nums = [f["num_implan"] for f in filas]
        obs = []
        if totales != [suma]:
            obs.append(f"TOTAL NO CUADRA (totales impresos: {totales})")
            ok = False
        faltan = sorted(set(range(1, max(nums) + 1)) - set(nums))
        if faltan:
            obs.append(f"numeración sin {faltan}")
        if len(nums) != len(set(nums)):
            obs.append("números repetidos")
        if raras:
            ok = False
            obs.append(f"{len(raras)} líneas sin leer: {raras}")
        print(f"{unidad:<26}{len(filas):>6}{suma:>9,}{(totales or [0])[-1]:>9,}  {'; '.join(obs)}")
        todas += filas
    print(f"{'TOTAL':<26}{len(todas):>6}{sum(f['poblacion'] for f in todas):>9,}")

    with SALIDA.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["unidad", "num_implan", "localidad", "rango", "poblacion"])
        w.writeheader()
        w.writerows(todas)
    print(f"Escrito {SALIDA.relative_to(RAIZ)}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
