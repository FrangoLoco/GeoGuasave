# Plan de implementación de GeoGuasave

Este plan convierte la metodología de la tesis (sección 7.4 y los tres instrumentos de la 7.2) en fases de código. Cada fase tiene una lista de tareas, una lista de verificaciones que deben correrse y mostrarse, y puntos marcados con **Detente** donde hay que esperar mi revisión.

Las semanas entre paréntesis son las del cronograma de la tesis.

---

## Parámetros iniciales

Cualquier cambio a estos valores se anota en `docs/decisiones.md`.

| Parámetro | Valor | Origen |
|---|---|---|
| SRID de almacenamiento | 6372 | Proyección del Marco Geoestadístico 2022 |
| SRID de entrada | 4326 | Coordenadas GPS |
| Clave del municipio | entidad 25, municipio 011 | Clave INEGI de Guasave |
| Distancia máxima a localidad puntual (lpr) | 500 m, configurable con `LPR_MAX_DIST_M` | Propuesta; en la tesis se reporta también con 250 m y 1,000 m |
| Tolerancia para huecos y traslapes | 1 m | Advertencia del INEGI |
| Densificación de bordes para Voronoi | 50 m | Propuesta |
| Semilla aleatoria | 2026 | Reproducibilidad de muestras y pruebas de carga |
| Meta de rendimiento (H3) | p95 < 200 ms con 50 usuarios concurrentes | Hipótesis H3 |

---

## Contrato de la API

`GET /reverse?lat=<float>&lon=<float>`

Respuesta 200 para un punto dentro de Guasave (valores de ejemplo):

```json
{
  "municipio":   { "cvegeo": "25011", "nombre": "Guasave" },
  "fuera_de_guasave": false,
  "sindicatura": { "nombre": "Alcaldía Central", "origen": "implan" },
  "localidad":   { "cvegeo": "250110001", "nombre": "Guasave", "ambito": "U" },
  "ageb":        { "cvegeo": "250110001XXXX", "tipo": "U" },
  "metodo": "poligono_localidad",
  "distancia_m": null,
  "atribucion": "Fuente: INEGI, Marco Geoestadístico 2022; IMPLAN Guasave, Cartografía de sindicaturas."
}
```

Reglas del contrato:

- `metodo` vale `poligono_localidad`, `poligono_externo`, `localidad_puntual` o `fuera_de_localidad`.
- `distancia_m` solo se llena con `localidad_puntual` (distancia en metros al punto de la localidad). En los demás casos es `null`.
- `localidad` es `null` cuando `metodo` es `fuera_de_localidad`.
- `sindicatura.origen` vale `implan` cuando la localidad aparece en una tabla del IMPLAN, o `voronoi` cuando la sindicatura se aproximó con los polígonos de Voronoi.
- Punto dentro de Sinaloa pero fuera de Guasave: respuesta 200 con `municipio`, `fuera_de_guasave: true` y los demás campos en `null`.
- Punto fuera de Sinaloa o coordenadas inválidas: respuesta 422 con un mensaje claro.
- `GET /health` informa el estado de la API y de la base de datos.

---

## Reglas de asignación (tesis 7.4)

Con el punto `p` ya transformado a EPSG:6372:

1. **Localidad.** Se prueba en este orden y gana la primera regla que aplique:
   1. Polígono de localidad (capa `l`) que contiene `p`, con tolerancia de 1 m.
   2. Polígono externo (capas `pe` o `pem`) que contiene `p`, con tolerancia de 1 m.
   3. Localidad puntual (capa `lpr`) más cercana, a no más de `LPR_MAX_DIST_M`.
   4. Si nada aplica, `fuera_de_localidad`.

   Si hay más de un candidato en una misma regla, el desempate es: menor distancia, luego menor área, luego `CVEGEO` ascendente.
2. **Sindicatura.** Es la de la localidad asignada. Si no hay localidad, o la localidad no aparece en las tablas del IMPLAN, se usa el polígono de Voronoi que contiene `p`.
3. **AGEB.** Se obtiene cruzando `p` con las capas `a` (urbanas) y `ar` (rurales). Si `p` cae en una AGEB urbana, gana la urbana. Nunca se toma de los atributos de la localidad, porque algunas localidades rebasan su AGEB.
4. **Municipio.** Se obtiene cruzando `p` con la capa `mun`. Nunca se toma de los atributos de la localidad, porque El Zopilote (250110291) rebasa el límite municipal.

---

## Estructura del repositorio

```
geoguasave/
├── CLAUDE.md
├── README.md
├── docker-compose.yml
├── .env.example
├── data/
│   ├── raw/            # zip del INEGI sin modificar (no se sube a git)
│   ├── manual/         # tablas del IMPLAN, emparejamiento revisado, Bamoa digitalizado
│   └── eval_raw/       # respuestas crudas de Google y Nominatim (no se sube a git)
├── db/
│   ├── init/           # extensiones y esquema geo
│   └── sql/            # reverse_geocode, Voronoi y vistas
├── etl/                # carga de capas y emparejamiento de sindicaturas
├── api/                # backend elegido en la Fase 4
├── bench/              # prototipos FastAPI y Node de la prueba preliminar
├── tests/
├── eval/
│   ├── muestra/        # Instrumento 1: puntos de control y comparación
│   ├── k6/             # Instrumento 2: pruebas de carga
│   └── costos/         # Instrumento 3: modelo de costos
└── docs/
    ├── PLAN.md
    └── decisiones.md
```

---

## Fase 0. Esqueleto del proyecto (S1–2)

Tareas:

- Crear la estructura de carpetas de arriba, un `.gitignore` (que excluya `data/raw/`, `data/eval_raw/` y `.env`), un `.env.example` y un `README.md` breve.
- `docker-compose.yml` con un servicio `db` (PostGIS con versión de imagen fija y volumen persistente) y un servicio `gdal` para herramientas (imagen oficial `ghcr.io/osgeo/gdal` con versión fija).
- Script de inicialización que crea las extensiones necesarias y el esquema `geo`.
- `docs/decisiones.md` con su primera entrada: las versiones elegidas de PostGIS y GDAL.

Terminado cuando:

- `docker compose up -d db` levanta la base y `SELECT postgis_full_version();` responde.
- El contenedor de GDAL ejecuta `ogrinfo --version`.
- La sección "Comandos" de `CLAUDE.md` tiene los comandos reales.

---

## Fase 1. Carga del Marco Geoestadístico (S1–6)

Requiere: el zip del Marco Geoestadístico de diciembre de 2022 de Sinaloa en `data/raw/`.

Tareas:

1. Descomprimir y listar las capas y sus campos con `ogrinfo -so`. **Detente** y repórtame qué capas y campos encontraste. Si falta alguna de `mun`, `l`, `pe`, `pem`, `lpr`, `a` o `ar`, no sigas.
2. Escribir un script de carga idempotente (que se pueda correr varias veces con el mismo resultado) que importe las siete capas de **todo Sinaloa** al esquema `geo`, en EPSG:6372. Se carga el estado completo para resolver bien los bordes con municipios vecinos y para responder `fuera_de_guasave`.
3. Verificar la codificación: los acentos y la ñ de los nombres deben verse bien. Si no, reimportar con la codificación correcta y anotarlo.
4. Validar geometrías con `ST_IsValid`; repararlas con `ST_MakeValid` y anotar cuántas se repararon.
5. Crear índices GiST en todas las geometrías y correr `ANALYZE`.

Terminado cuando (mostrar la salida de cada consulta):

- Conteo de elementos por capa, para Sinaloa y para Guasave.
- En la capa `l` de Guasave hay 201 localidades: 17 urbanas y 184 rurales, como dice la tesis. Si la cifra no coincide, repórtala; no la "ajustes".
- El Zopilote (250110291) no queda contenido en el polígono municipal de Guasave.
- Si el zip incluye catálogos de casos especiales, comparar con ellos: 15 localidades rurales de Guasave que rebasan su AGEB.
- Todas las geometrías tienen SRID 6372 y son válidas.

---

## Fase 2. Sindicaturas (S3–6)

Requiere: las tablas del IMPLAN de las 13 unidades (12 sindicaturas y la Alcaldía Central) en `data/manual/implan/`, en el formato que sea (PDF, imagen o captura de la página).

Tareas:

1. **Transcripción.** Pasar las tablas a `data/manual/implan_localidades.csv` con las columnas `unidad`, `localidad`, `rango` y `poblacion`. Comprobar totales por unidad; por ejemplo, Bamoa debe tener 18 localidades y 7,963 habitantes. **Detente** para que yo revise la transcripción contra el original.
2. **Emparejamiento con claves del INEGI.** Normalizar nombres (minúsculas, sin acentos, sin prefijos como "Ejido") solo para comparar. Buscar primero coincidencia exacta normalizada en la capa `l` de Guasave, luego en `lpr`, y después coincidencia aproximada (por ejemplo, con `rapidfuzz`) con un umbral anotado. Generar `data/manual/localidad_sindicatura.csv` con `cvegeo`, `nombre_inegi`, `nombre_implan`, `unidad`, `metodo_match` (exacto, aproximado o manual) y `puntaje`.
   - Prueba de control: reproducir el resultado de la tesis para Bamoa (10 de 18 localidades coinciden por nombre exacto con la capa `l`; las demás se buscan en `lpr`).
   - Los casos aproximados o ambiguos van a `data/manual/revision_emparejamiento.csv`. **Detente** para que yo los resuelva.
3. **Localidades sin sindicatura.** Listar las localidades del INEGI en Guasave que no aparecen en ninguna tabla del IMPLAN. Su sindicatura se asignará por Voronoi, con `origen = 'voronoi'`.
4. **Polígonos de Voronoi.** Generadores: vértices de los bordes de los polígonos `l`, `pe` y `pem` densificados cada 50 m, más los puntos `lpr`, solo de localidades con sindicatura del IMPLAN. Calcular `ST_VoronoiPolygons`, unir las celdas por sindicatura y recortar al polígono municipal de Guasave. Guardar en `geo.sindicatura_poligono`.
5. **Validación con Bamoa.** Cuando exista `data/manual/bamoa_implan.geojson` (lo digitalizo yo en QGIS a partir del mapa del IMPLAN), calcular el área compartida entre ese polígono y el de Voronoi de Bamoa: intersección sobre el área del IMPLAN, intersección sobre el área de Voronoi e intersección sobre unión. Si el archivo aún no existe, dejar el script listo.

Terminado cuando:

- Hay 13 polígonos de sindicatura que cubren el municipio sin huecos ni traslapes (la suma de áreas difiere del área municipal en menos de 0.01 %).
- Tabla resumen del emparejamiento: cuántas localidades fueron exactas, aproximadas, manuales y sin emparejar.
- Toda localidad del INEGI en Guasave tiene una sindicatura, con su origen.

---

## Fase 3. Función de geocodificación (S3–8)

Tareas:

- Implementar `geo.reverse_geocode(lon, lat, lpr_max_m DEFAULT 500)` en SQL o PL/pgSQL. Devuelve los campos del contrato (la atribución la agrega la API) siguiendo las reglas de asignación de arriba.
- Pruebas automáticas en `tests/` que corren contra la base de datos.

Pruebas mínimas:

- Para cada localidad poligonal de Guasave, `ST_PointOnSurface` de su polígono devuelve esa localidad con `poligono_localidad`. Las excepciones por traslapes van en una lista explícita con su motivo.
- Para cada localidad puntual de Guasave, un punto desplazado 50 m devuelve esa localidad con `localidad_puntual` y `distancia_m` cercana a 50, salvo que caiga dentro de un polígono.
- Un punto alejado de toda localidad devuelve `fuera_de_localidad` con sindicatura de origen `voronoi`.
- Un punto en la ciudad de Guasave devuelve un AGEB urbano cuya clave de 13 caracteres empieza con 250110001.
- La parte de El Zopilote fuera de Guasave devuelve el municipio vecino.
- Un punto en otro municipio de Sinaloa devuelve `fuera_de_guasave: true`; un punto fuera de Sinaloa no devuelve resultado.
- El mismo punto consultado dos veces da exactamente la misma respuesta.
- `EXPLAIN ANALYZE` de una consulta típica muestra que se usan los índices GiST.

Terminado cuando todas las pruebas pasan y se muestra la salida.

---

## Fase 4. API y Docker (S3–8)

Tareas:

1. **Prueba preliminar de backend** (la tesis dice que el backend se elige con ella). Construir dos prototipos mínimos de `GET /reverse`, uno en FastAPI y otro en Node.js, que llamen a `geo.reverse_geocode` con un pool de conexiones. Correr el mismo script de k6 contra cada uno: 50 usuarios virtuales durante 1 minuto, 3 repeticiones, en la misma máquina. Anotar p95 y solicitudes por segundo en `docs/decisiones.md`. **Detente** y muéstrame la tabla; yo elijo el backend.
2. **API final** con el backend elegido:
   - Validación de parámetros (lat entre −90 y 90, lon entre −180 y 180) y errores 422.
   - Atribución en cada respuesta, `GET /health`, documentación OpenAPI y CORS abierto (es una API abierta).
   - `LPR_MAX_DIST_M` configurable desde el entorno.
   - Registro de cada solicitud con su latencia.
3. **Docker Compose** con `db` y `api`, y un comando documentado en el README que levanta todo desde cero con los datos cargados.

Terminado cuando:

- Las pruebas de la API pasan.
- Un `curl` a `/reverse` con un punto de la ciudad de Guasave devuelve el contrato completo.
- Siguiendo solo el README, desde un clon limpio y con el zip en `data/raw/`, el servicio queda funcionando.

---

## Fase 5. Muestra de puntos de control (S5–8)

Requiere: el zip de la *Información vectorial de localidades amanzanadas y números exteriores 2023* de Sinaloa en `data/raw/`.

Tareas: un script en `eval/muestra/` con la semilla fija genera 400 puntos:

- 200 puntos al azar de la capa de números exteriores de Guasave. Su localidad de referencia son los primeros 9 caracteres de la clave de su manzana (verificar el nombre real del campo).
- 150 puntos al azar en zona rural: dentro del municipio y fuera de los polígonos de localidades urbanas.
- 50 puntos al azar a menos de 100 m de un límite de localidad, por dentro o por fuera.

Cada punto lleva `estrato`, `lat`, `lon`, municipio, sindicatura y localidad de referencia (o `null` si no cae en ninguna localidad, en cuyo caso solo se evalúan municipio y sindicatura). Salida: `eval/muestra/puntos_control.csv`, que sí se sube a git.

Terminado cuando:

- Hay 400 filas: 200, 150 y 50 por estrato, sin duplicados y todas dentro de Guasave.
- Se reporta cuántos de los 200 puntos de números exteriores caen en localidades urbanas y cuántos en rurales (dato que se usa para H2).

---

## Fase 6. Instrumentos de evaluación (S9–12)

### 6a. Instrumento 1: precisión

- Script que consulta GeoGuasave, la Geocoding API de Google (inversa, `language=es`, clave desde `.env`) y Nominatim (inversa, máximo 1 solicitud por segundo, con un User-Agent que identifique la aplicación y sin datos personales) con los 400 puntos.
- Guarda las respuestas crudas en `data/eval_raw/` y reutiliza lo ya consultado para no repetir llamadas. Incluye un modo de prueba que no llama a Google. **Detente** y pide confirmación antes de la corrida real contra Google.
- Extrae de cada respuesta los nombres candidatos (en Google, componentes como `locality`, `sublocality` y `administrative_area_level_2`; en Nominatim, `city`, `town`, `village`, `hamlet` y `county`), los normaliza y los empareja con el catálogo del INEGI. La sindicatura de Google y Nominatim se deriva de la localidad que devuelven, con la tabla del IMPLAN. Los casos ambiguos van a un CSV de revisión manual. **Detente** para que yo los resuelva.
- Calcula la tasa de acierto por nivel (municipio, sindicatura, localidad) y por estrato, la prueba de McNemar exacta pareada (GeoGuasave contra Google y GeoGuasave contra Nominatim) y el intervalo de confianza al 95 % de la diferencia pareada. El margen de no inferioridad para H1 queda como parámetro pendiente; lo defino con mi asesor.

### 6b. Instrumento 2: pruebas de carga con k6

- Coordenadas aleatorias dentro de Guasave, generadas con la semilla y guardadas en un archivo JSON que lee el script.
- Escenario A: rampa de 1 a 200 usuarios virtuales para encontrar la capacidad.
- Escenario B: 50 usuarios virtuales constantes durante 5 minutos, con el umbral `p(95) < 200` ms (H3).
- 3 repeticiones de cada escenario; los resúmenes se exportan en JSON a `eval/k6/resultados/`.
- La corrida oficial se hace en el servidor virtual de 2 vCPU y 4 GB que yo proporcione. En local solo se prueba que el script funcione.

### 6c. Instrumento 3: modelo de costos

- Archivo de configuración con las tarifas y su fecha de consulta: Google (Tabla 1 de la tesis), Mapbox, servidor virtual, almacenamiento y horas de mantenimiento por costo por hora.
- Script que calcula el costo mensual con 10,000, 100,000 y 1,000,000 de consultas, el volumen de equilibrio frente a Google y un análisis de sensibilidad variando las horas de mantenimiento. Genera un CSV y una gráfica.

Terminado cuando el modelo reproduce los ejemplos de la tesis:

- Google con 100,000 consultas: 450 dólares al mes.
- Google con 1,000,000 de consultas: 3,550 dólares al mes.
- Con un costo fijo de 30 dólares al mes, el equilibrio con Google está en 16,000 consultas.
