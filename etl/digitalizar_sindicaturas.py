"""Digitaliza los polígonos de las 13 sindicaturas de los mapas del IMPLAN (Fase 5).

Fuente: https://guasave.gob.mx/implan/cartografia-de-sindicaturas/ (mapas "micro" y
"macro"), guardados en data/manual/implan/mapas/. Son capturas de Google Earth con la
"EXTENSION TERRITORIAL" de la sindicatura en un color translúcido y sus localidades
marcadas. Configuración por mapa en data/manual/implan/mapas/digitalizacion.json.

Por cada mapa:
  1. Extrae la imagen del PDF (verifica su SHA-256).
  2. Georreferencia afín por mínimos cuadrados con puntos de control: localidades
     marcadas en el mapa y su punto del INEGI (lpr, o ST_PointOnSurface de l si no
     tiene). La posición del marcador se lee a mano (aproximada) y el script la afina
     al centroide de la mancha del color del marcador. Imprime residuos y RMS.
  3. Segmenta el relleno con un discriminante lineal de Fisher sobre ln(R/G), ln(B/G)
     e intensidad, entrenado
     con recuadros de muestra dentro y fuera del polígono; filtro de mayoría, apertura
     morfológica opcional (corta puentes angostos hacia zonas mal clasificadas) y cierre
     morfológico para rellenar marcadores y etiquetas. Vectoriza con gdal.Polygonize,
     toma el polígono mayor sin huecos y lo simplifica (1 px).
Si el relleno no se puede separar por color (Alcaldía Central: verde translúcido sobre
cultivos verdes), el polígono se da como "trazo": vértices leídos a mano sobre el borde
visible, con ayuda de una imagen del cociente de color suavizado.
Si una sindicatura tiene dos mapas (el "micro" corta el polígono), el polígono final es
el del primero más la parte del segundo que queda fuera del encuadre del primero.

Salida: GeoJSON (EPSG:6372) con una entidad por sindicatura, por stdout; mensajes por
stderr. Corre en el contenedor GDAL:
  docker compose run --rm -q -v "$PWD/etl:/etl:ro" gdal python3 /etl/digitalizar_sindicaturas.py \
    > data/manual/sindicaturas_implan.geojson
"""
import hashlib
import json
import os
import re
import sys
import zlib
from collections import deque

import numpy as np
from osgeo import gdal, ogr

gdal.UseExceptions()
CARPETA = "/data/manual/implan/mapas"
VENTANA = 40  # px alrededor de la posición leída para afinar el marcador
ATIPICO_M = 500  # residuo a partir del cual un punto de control se descarta (uno a la vez)
REVISION = os.environ.get("REVISION")  # carpeta opcional para imágenes de revisión


def log(*a):
    print(*a, file=sys.stderr)


def imagen(archivo, sha256):
    pdf = open(f"{CARPETA}/{archivo}", "rb").read()
    if hashlib.sha256(pdf).hexdigest() != sha256:
        sys.exit(f"El SHA-256 de {archivo} no coincide")
    m = re.search(rb"/Filter \[/FlateDecode /DCTDecode\].*?stream\r?\n", pdf, re.S)
    gdal.FileFromMemBuffer("/vsimem/mapa.jpg", zlib.decompressobj().decompress(pdf[m.end():]))
    ds = gdal.Open("/vsimem/mapa.jpg")
    a = np.dstack([ds.GetRasterBand(i).ReadAsArray() for i in (1, 2, 3)]).astype(float)
    gdal.Unlink("/vsimem/mapa.jpg")
    return a


def afinar(a, x, y, tol=45):
    """Centroide de la mancha conexa del color del marcador que contiene (x, y)."""
    h, w, _ = a.shape
    x0, y0 = max(0, x - VENTANA), max(0, y - VENTANA)
    win = a[y0:min(h, y + VENTANA), x0:min(w, x + VENTANA)]
    c = np.median(a[y - 2:y + 3, x - 2:x + 3].reshape(-1, 3), axis=0)
    m = np.linalg.norm(win - c, axis=2) < tol
    sy, sx = y - y0, x - x0
    if not m[sy, sx]:
        return x, y, 0
    vis = np.zeros_like(m)
    q = deque([(sy, sx)]); vis[sy, sx] = True; pts = []
    while q:
        cy, cx = q.popleft(); pts.append((cy, cx))
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ny, nx = cy + dy, cx + dx
            if 0 <= ny < m.shape[0] and 0 <= nx < m.shape[1] and m[ny, nx] and not vis[ny, nx]:
                vis[ny, nx] = True; q.append((ny, nx))
    p = np.array(pts)
    if len(p) < 15 or len(p) > (2 * VENTANA) ** 2 * 0.6:  # no es un marcador
        return x, y, len(p)
    return x0 + p[:, 1].mean(), y0 + p[:, 0].mean(), len(p)


def puntos_inegi(claves):
    ds = ogr.Open("PG:")
    lista = ",".join(f"'{c}'" for c in claves)
    lyr = ds.ExecuteSQL(
        "SELECT k.cvegeo, ST_X(s.g) AS x, ST_Y(s.g) AS y "
        f"FROM unnest(ARRAY[{lista}]) AS k(cvegeo), LATERAL (SELECT coalesce("
        "(SELECT geom FROM geo.localidad_puntual WHERE left(cvegeo, 9) = k.cvegeo), "
        "(SELECT ST_PointOnSurface(geom) FROM geo.localidad WHERE cvegeo = k.cvegeo)) AS g) s")
    r = {f["cvegeo"]: (f["x"], f["y"]) for f in lyr if f["x"] is not None}
    ds.ReleaseResultSet(lyr)
    return r


def filtro_max(m, k):
    r = k // 2
    for eje in (0, 1):
        p = np.pad(m, [(r, r) if e == eje else (0, 0) for e in (0, 1)])
        out = np.zeros_like(m)
        for i in range(k):
            out |= np.take(p, range(i, i + m.shape[eje]), axis=eje)
        m = out
    return m


def mayoria(m, k):
    r = k // 2
    c = np.pad(m.astype(np.int32), r).cumsum(0).cumsum(1)
    c = np.pad(c, ((1, 0), (1, 0)))
    return (c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]) > (k * k) // 2


def rasgos(a):
    """Cocientes de color e intensidad: el relleno translúcido cambia sobre todo el tono."""
    r, g, b = a[..., 0] + 1, a[..., 1] + 1, a[..., 2] + 1
    return np.stack([np.log(r / g), np.log(b / g), np.log(r + g + b)], axis=-1)


def rasterizar(poligonos, forma):
    """Máscara de polígonos dados en píxeles [[x, y], ...]."""
    v = ogr.GetDriverByName("Memory").CreateDataSource("")
    capa = v.CreateLayer("i")
    for vertices in poligonos:
        anillo = ogr.Geometry(ogr.wkbLinearRing)
        for x, y in vertices + vertices[:1]:
            anillo.AddPoint_2D(x, y)
        p = ogr.Geometry(ogr.wkbPolygon); p.AddGeometry(anillo)
        f = ogr.Feature(capa.GetLayerDefn()); f.SetGeometry(p); capa.CreateFeature(f)
    r = gdal.GetDriverByName("MEM").Create("", forma[1], forma[0], 1, gdal.GDT_Byte)
    r.SetGeoTransform((0, 1, 0, 0, 0, 1))
    gdal.RasterizeLayer(r, [1], capa, burn_values=[1])
    return r.GetRasterBand(1).ReadAsArray().astype(bool)


def muestras(f, cajas):
    return np.concatenate([f[y0:y1, x0:x1].reshape(-1, f.shape[-1]) for x0, y0, x1, y1 in cajas])


def media_local(x, k):
    r = k // 2
    c = np.pad(x, r, mode="edge").cumsum(0).cumsum(1)
    c = np.pad(c, ((1, 0), (1, 0)))
    return (c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]) / (k * k)


def rasgos_locales(f, k):
    """Media local de cada rasgo y desviación estándar local de la intensidad: el relleno
    translúcido baja el contraste de lo que hay debajo."""
    medias = [media_local(f[..., i], k) for i in range(f.shape[-1])]
    var = media_local(f[..., 2] ** 2, k) - medias[2] ** 2
    return np.stack(medias + [np.log(np.sqrt(np.maximum(var, 0)) + 1e-3)], axis=-1)


def mascara(a, cfg):
    a = rasgos(a)
    if cfg.get("ventana_local"):  # opcional: rasgos de vecindad (k x k px)
        a = rasgos_locales(a, cfg["ventana_local"])
    dentro, fuera = muestras(a, cfg["dentro"]), muestras(a, cfg["fuera"])
    sw = np.cov(dentro.T) + np.cov(fuera.T)
    w = np.linalg.solve(sw, dentro.mean(0) - fuera.mean(0))
    t = (dentro.mean(0) @ w + fuera.mean(0) @ w) / 2
    acierto = ((dentro @ w > t).mean() + (fuera @ w <= t).mean()) / 2
    m = a @ w > t
    for x0, y0, x1, y1 in cfg.get("excluir", []):  # título, leyenda, escala
        m[y0:y1, x0:x1] = False
    m = mayoria(m, cfg.get("mayoria", 9))
    if cfg.get("incluir"):  # zonas del relleno tapadas por marcadores y etiquetas, marcadas a mano
        m |= rasterizar(cfg["incluir"], m.shape)
    if cfg.get("apertura"):  # corta puentes angostos hacia zonas mal clasificadas
        k = cfg["apertura"]
        m = filtro_max(~filtro_max(~m, k), k)
    k = cfg["cierre"]
    return ~filtro_max(~filtro_max(m, k), k), acierto


def poligono_pixeles(m, semilla):
    drv = gdal.GetDriverByName("MEM")
    r = drv.Create("", m.shape[1], m.shape[0], 1, gdal.GDT_Byte)
    r.SetGeoTransform((0, 1, 0, 0, 0, 1))
    r.GetRasterBand(1).WriteArray(m.astype(np.uint8))
    v = ogr.GetDriverByName("Memory").CreateDataSource("")
    capa = v.CreateLayer("p")
    capa.CreateField(ogr.FieldDefn("v", ogr.OFTInteger))
    gdal.Polygonize(r.GetRasterBand(1), r.GetRasterBand(1), capa, 0)
    p = ogr.Geometry(ogr.wkbPoint); p.AddPoint_2D(*semilla)
    cands = [f.GetGeometryRef().Clone() for f in capa]
    elegido = [g for g in cands if g.Contains(p)] or [max(cands, key=lambda g: g.GetArea())]
    pol = ogr.Geometry(ogr.wkbPolygon)
    pol.AddGeometry(elegido[0].GetGeometryRef(0))  # sin huecos
    return pol.SimplifyPreserveTopology(1)


def revisar(a, pol, px, cfg, salida):
    """Imagen con el contorno (magenta), los puntos de control afinados (cian) y las muestras."""
    o = a.astype(np.uint8).copy()
    h, w, _ = o.shape
    g = 2 if w > 2000 else 1
    anillo = np.array(pol.GetGeometryRef(0).GetPoints())[:, :2]
    for (xa, ya), (xb, yb) in zip(anillo[:-1], anillo[1:]):
        n = int(max(abs(xb - xa), abs(yb - ya))) + 1
        for t in np.linspace(0, 1, n):
            x, y = int(xa + t * (xb - xa)), int(ya + t * (yb - ya))
            if 0 <= x < w and 0 <= y < h:  # un vértice extrapolado puede quedar fuera
                o[max(0, y - g):y + g + 1, max(0, x - g):x + g + 1] = (255, 0, 255)
    for x, y in px:
        x, y = int(x), int(y)
        o[max(0, y - 6 * g):y + 6 * g, max(0, x - g):x + g] = (0, 255, 255)
        o[max(0, y - g):y + g, max(0, x - 6 * g):x + 6 * g] = (0, 255, 255)
    for color, cajas in (((255, 255, 0), cfg.get("dentro", [])), ((255, 128, 0), cfg.get("fuera", []))):
        for x0, y0, x1, y1 in cajas:
            o[y0:y0 + g * 2, x0:x1] = color; o[y1 - g * 2:y1, x0:x1] = color
            o[y0:y1, x0:x0 + g * 2] = color; o[y0:y1, x1 - g * 2:x1] = color
    d = gdal.GetDriverByName("MEM").Create("", w, h, 3, gdal.GDT_Byte)
    for i in range(3):
        d.GetRasterBand(i + 1).WriteArray(o[..., i])
    gdal.GetDriverByName("JPEG").CreateCopy(salida, d, options=["QUALITY=80"])


def a_mundo(geom_px, A):
    g = geom_px.Clone()
    for i in range(g.GetGeometryCount()):
        anillo = g.GetGeometryRef(i)
        for j in range(anillo.GetPointCount()):
            x, y = anillo.GetX(j), anillo.GetY(j)
            X, Y = np.array([x, y, 1.0]) @ A
            anillo.SetPoint_2D(j, X, Y)
    return g


def rectangulo(w, h):
    r = ogr.Geometry(ogr.wkbLinearRing)
    for x, y in ((0, 0), (w, 0), (w, h), (0, h), (0, 0)):
        r.AddPoint_2D(x, y)
    p = ogr.Geometry(ogr.wkbPolygon); p.AddGeometry(r)
    return p


def procesar_mapa(nombre, cfg):
    a = imagen(cfg["archivo"], cfg["sha256"])
    h, w, _ = a.shape
    inegi = puntos_inegi([c for c, _, _ in cfg["gcp"]])
    px, mundo, etiquetas = [], [], []
    for c, x, y in cfg["gcp"]:
        if c not in inegi:
            sys.exit(f"{nombre}: {c} sin punto del INEGI")
        # "afinar": false cuando los marcadores se confunden con el relleno (se usa la lectura).
        fx, fy, n = afinar(a, x, y) if cfg.get("afinar", True) else (x, y, 0)
        px.append((fx, fy)); mundo.append(inegi[c]); etiquetas.append((c, x, y, fx, fy, n))
    P = np.c_[np.array(px), np.ones(len(px))]
    W = np.array(mundo)
    usar = np.ones(len(px), bool)
    while True:  # descarta el peor punto mientras pase de ATIPICO_M (marcador mal leído)
        A = np.linalg.lstsq(P[usar], W[usar], rcond=None)[0]
        res = np.linalg.norm(P @ A - W, axis=1)
        peor = np.argmax(np.where(usar, res, -1))
        if res[peor] <= ATIPICO_M or usar.sum() <= 4:
            break
        usar[peor] = False
    rms = float(np.sqrt((res[usar] ** 2).mean()))
    px = [p for p, u in zip(px, usar) if u]
    log(f"{nombre} [{cfg['archivo']}] {w}x{h}: {usar.sum()} de {len(usar)} puntos de control, RMS {rms:.1f} m, "
        f"máx {res[usar].max():.1f} m, {np.hypot(*A[0]):.2f} x {np.hypot(*A[1]):.2f} m/px")
    for (c, x, y, fx, fy, n), e, u in zip(etiquetas, res, usar):
        log(f"    {c} leído ({x},{y}) afinado ({fx:.1f},{fy:.1f}) [{n} px]  residuo {e:7.1f} m"
            + ("" if u else "  DESCARTADO"))

    if cfg.get("trazo"):  # vértices trazados a mano sobre el borde visible
        anillo = ogr.Geometry(ogr.wkbLinearRing)
        for x, y in cfg["trazo"] + cfg["trazo"][:1]:
            anillo.AddPoint_2D(x, y)
        pol = ogr.Geometry(ogr.wkbPolygon); pol.AddGeometry(anillo)
        acierto = float("nan")
    else:
        m, acierto = mascara(a, cfg)
        b0 = cfg["dentro"][0]
        pol = poligono_pixeles(m, ((b0[0] + b0[2]) / 2, (b0[1] + b0[3]) / 2))
    x0, x1, y0, y1 = pol.GetEnvelope()
    borde = x0 <= 1 or y0 <= 1 or x1 >= w - 1 or y1 >= h - 1
    if REVISION:
        revisar(a, pol, px, cfg, f"{REVISION}/{nombre}_{cfg['archivo'][:-4]}.jpg")
    log(f"    {'trazo a mano' if cfg.get('trazo') else f'segmentación: acierto en muestras {100 * acierto:.1f} %'}; "
        f"toca el borde de la imagen: {'sí' if borde else 'no'}")
    return {"pol": a_mundo(pol, A), "marco": a_mundo(rectangulo(w, h), A), "rms": round(rms, 1),
            "gcp": len(px), "archivo": cfg["archivo"], "borde": borde}


def main():
    cfg = json.load(open(f"{CARPETA}/digitalizacion.json", encoding="utf-8"))
    solo = sys.argv[1:]  # opcional: nombres de sindicatura a procesar
    entidades = []
    for nombre, c in cfg["sindicaturas"].items():
        if solo and nombre not in solo:
            continue
        piezas = [procesar_mapa(nombre, m) for m in c["mapas"]]
        final = piezas[0]["pol"]
        for p in piezas[1:]:
            final = final.Union(p["pol"].Difference(piezas[0]["marco"]))
        final = final.MakeValid() if not final.IsValid() else final
        log(f"  => {nombre}: {final.GetArea() / 1e6:.2f} km²")
        entidades.append({
            "type": "Feature",
            "properties": {
                "sindicatura": nombre,
                "mapas": [p["archivo"] for p in piezas],
                "gcp": [p["gcp"] for p in piezas],
                "rms_m": [p["rms"] for p in piezas],
                "toca_borde": [p["borde"] for p in piezas],
            },
            "geometry": json.loads(final.ExportToJson(options=["COORDINATE_PRECISION=1"])),
        })
    json.dump({"type": "FeatureCollection",
               "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::6372"}},
               "features": entidades}, sys.stdout, ensure_ascii=False)
    print()


if __name__ == "__main__":
    main()
