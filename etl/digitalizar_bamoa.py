"""Digitaliza el polígono de Bamoa del mapa "micro" del IMPLAN (Fase 2, paso 5).

Fuente: https://guasave.gob.mx/implan/cartografia-de-sindicaturas/ ->
"03 SIND. BAMOA MICRO.pdf", una captura de Google Earth de 1920x1080 px con la
"EXTENSION TERRITORIAL BAMOA" en verde translúcido y 11 localidades marcadas.

Pasos:
  1. Extrae el JPEG del PDF (flujo FlateDecode + DCTDecode).
  2. Georreferencia: ajuste afín píxel -> EPSG:6372 por mínimos cuadrados con
     los 11 marcadores de localidad y su punto lpr del INEGI. El centro de cada
     marcador es el centroide de su color en una ventana alrededor de una
     posición aproximada. Imprime los residuos y el RMS.
  3. Segmenta el verde por color (B/G < 0.6 y G - B > 35), quita grumos con un
     filtro de mayoría y hace un cierre morfológico para rellenar las muescas
     que dejan los marcadores y etiquetas dibujados sobre el borde.
  4. Vectoriza con gdal.Polygonize, toma el polígono mayor sin huecos y lo
     simplifica (Douglas-Peucker, 1 px).
Salida: GeoJSON en EPSG:6372 por stdout; mensajes por stderr.

Corre en el contenedor GDAL (numpy + bindings de GDAL, versión fijada):
  docker compose run --rm -q -v "$PWD/etl:/etl:ro" gdal python3 /etl/digitalizar_bamoa.py \
    > data/manual/bamoa_implan.geojson
"""
import hashlib
import json
import re
import sys
import zlib

import numpy as np
from osgeo import gdal, ogr

gdal.UseExceptions()
PDF = "/data/manual/implan/mapas/03 SIND. BAMOA MICRO.pdf"
SHA256 = "948b62adaf5b06867041f182f78948ace2092cde03c7a3a798a76b156fb78487"

# cvegeo -> (nombre, x, y aproximados en píxeles, tipo de marcador)
MARCADORES = {
    "250110052": ("Bamoa", 942, 270, "turquesa"),
    "250110181": ("Orba (Infiernito)", 808, 410, "turquesa"),
    "250110097": ("Cruz Blanca", 748, 492, "turquesa"),
    "250110312": ("Choipa", 1121, 835, "turquesa"),
    "250110216": ("Ranchito de Zavala", 1077, 190, "oscuro"),
    "250111222": ("La Abundancia", 1053, 288, "oscuro"),
    "250110998": ("Tahuilana (El Chorizo)", 1001, 609, "oscuro"),
    "250111031": ("Norotillos", 1111, 646, "oscuro"),
    "250110301": ("Herculano de la Rocha", 1144, 809, "oscuro"),
    "250110308": ("Los Gavilanes", 890, 957, "oscuro"),
    "250110178": ("Norotío (El Gato)", 986, 980, "oscuro"),
}
VENTANA = 25    # px alrededor de la posición aproximada
CIERRE = 31     # lado del cierre, px (~500 m): cubre el diámetro de los marcadores del borde (~28 px)
SIMPLIFICA = 1  # tolerancia de Douglas-Peucker, px


def log(*a):
    print(*a, file=sys.stderr)


def imagen():
    pdf = open(PDF, "rb").read()
    if hashlib.sha256(pdf).hexdigest() != SHA256:
        sys.exit(f"El SHA-256 de {PDF} no coincide")
    m = re.search(rb"/Filter \[/FlateDecode /DCTDecode\].*?stream\r?\n", pdf, re.S)
    jpeg = zlib.decompressobj().decompress(pdf[m.end():])
    gdal.FileFromMemBuffer("/vsimem/mapa.jpg", jpeg)
    ds = gdal.Open("/vsimem/mapa.jpg")
    return np.dstack([ds.GetRasterBand(i).ReadAsArray() for i in (1, 2, 3)]).astype(float)


def centro(a, x, y, tipo):
    w = a[y - VENTANA:y + VENTANA, x - VENTANA:x + VENTANA]
    r, g, b = w[..., 0], w[..., 1], w[..., 2]
    if tipo == "turquesa":
        m = (r < 60) & (g > 110) & (g > b)
    else:
        m = (r < 35) & (g < 60) & (b < 50) & (g > r + 5)
    ys, xs = np.nonzero(m)
    return x - VENTANA + xs.mean(), y - VENTANA + ys.mean()


def puntos_inegi():
    ds = ogr.Open("PG:")
    claves = ",".join(f"'{c}'" for c in MARCADORES)
    # Punto lpr; si la localidad no tiene (Bamoa, urbana), ST_PointOnSurface de su polígono l.
    lyr = ds.ExecuteSQL(
        "SELECT k.cvegeo, ST_X(s.g) AS x, ST_Y(s.g) AS y "
        f"FROM unnest(ARRAY[{claves}]) AS k(cvegeo), LATERAL (SELECT coalesce("
        "(SELECT geom FROM geo.localidad_puntual WHERE left(cvegeo, 9) = k.cvegeo), "
        "(SELECT ST_PointOnSurface(geom) FROM geo.localidad WHERE cvegeo = k.cvegeo)) AS g) s")
    return {f["cvegeo"]: (f["x"], f["y"]) for f in lyr}


def filtro_max(m, k):
    """Máximo en una ventana cuadrada k x k (dilatación binaria), separable."""
    r = k // 2
    for eje in (0, 1):
        p = np.pad(m, [(r, r) if e == eje else (0, 0) for e in (0, 1)])
        m = np.max([np.take(p, range(i, i + m.shape[eje]), axis=eje) for i in range(k)], axis=0)
    return m


def main():
    a = imagen()
    inegi = puntos_inegi()
    claves = sorted(MARCADORES)
    if set(claves) - set(inegi):
        sys.exit(f"Sin punto lpr: {set(claves) - set(inegi)}")
    px = np.array([centro(a, *MARCADORES[c][1:]) for c in claves])
    mundo = np.array([inegi[c] for c in claves])
    P = np.c_[px, np.ones(len(px))]
    A = np.linalg.lstsq(P, mundo, rcond=None)[0]   # [x y 1] @ A = [X Y] en EPSG:6372
    res = np.linalg.norm(P @ A - mundo, axis=1)
    rms = float(np.sqrt((res ** 2).mean()))
    log(f"Georreferencia afín con {len(claves)} marcadores: RMS {rms:.1f} m, máx {res.max():.1f} m, "
        f"{np.hypot(*A[0]):.2f} x {np.hypot(*A[1]):.2f} m/px")
    for c, (x, y), e in zip(claves, px, res):
        log(f"  {c} {MARCADORES[c][0]:<24} píxel ({x:7.1f}, {y:6.1f})  residuo {e:6.1f} m")

    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    m = (b / (g + 1) < 0.6) & (g - b > 35)
    # Filtro de mayoría 9 x 9 para quitar grumos sueltos.
    c = np.pad(m.astype(np.int32), 4).cumsum(0).cumsum(1)
    c = np.pad(c, ((1, 0), (1, 0)))
    m = (c[9:, 9:] - c[:-9, 9:] - c[9:, :-9] + c[:-9, :-9]) > 40
    # Cierre: dilatación y luego erosión (= dilatación del complemento).
    cerrado = ~filtro_max(~filtro_max(m, CIERRE), CIERRE)
    log(f"Máscara: {m.sum()} px; tras el cierre: {cerrado.sum()} px (+{100 * (cerrado.sum() / m.sum() - 1):.2f} %)")

    drv = gdal.GetDriverByName("MEM")
    r_ds = drv.Create("", a.shape[1], a.shape[0], 1, gdal.GDT_Byte)
    r_ds.SetGeoTransform((0, 1, 0, 0, 0, 1))  # espacio de píxeles; y hacia abajo
    r_ds.GetRasterBand(1).WriteArray(cerrado.astype(np.uint8))
    v_ds = ogr.GetDriverByName("Memory").CreateDataSource("")
    capa = v_ds.CreateLayer("p")
    capa.CreateField(ogr.FieldDefn("v", ogr.OFTInteger))
    gdal.Polygonize(r_ds.GetRasterBand(1), r_ds.GetRasterBand(1), capa, 0)
    mayor = max((f.GetGeometryRef().Clone() for f in capa), key=lambda g: g.GetArea())
    anillo = mayor.GetGeometryRef(0)
    pol = ogr.Geometry(ogr.wkbPolygon)
    pol.AddGeometry(anillo)
    pol = pol.SimplifyPreserveTopology(SIMPLIFICA)
    xy = np.array(pol.GetGeometryRef(0).GetPoints())[:, :2]
    xy = np.c_[xy, np.ones(len(xy))] @ A
    log(f"Polígono: {len(xy)} vértices, {abs(ogr.CreateGeometryFromJson(json.dumps({'type': 'Polygon', 'coordinates': [xy.tolist()]})).GetArea()) / 1e6:.2f} km²")

    json.dump({
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::6372"}},
        "features": [{
            "type": "Feature",
            "properties": {
                "sindicatura": "Bamoa",
                "fuente": "IMPLAN Guasave, Cartografía de sindicaturas, 03 SIND. BAMOA MICRO.pdf",
                "metodo": "digitalizado por color con etl/digitalizar_bamoa.py",
                "gcp": len(claves), "rms_m": round(rms, 1),
            },
            "geometry": {"type": "Polygon", "coordinates": [[[round(x, 1), round(y, 1)] for x, y in xy]]},
        }],
    }, sys.stdout, ensure_ascii=False)
    print()


if __name__ == "__main__":
    main()
