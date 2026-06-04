# 🏄 Surf Monitor — costa de Barcelona

Monitor automático de condiciones de **surf** para varios spots de la costa de
Barcelona: **Castelldefels, Masnou y Sitges**. Cada 6 horas revisa la previsión
de cada spot, evalúa si hay una ventana surfeable **a partir de las próximas
3 horas** (el tiempo que necesitas para llegar en coche), puntúa su calidad con
**estrellas** y avisa por **Telegram** con un mensaje claro por cada spot que
tenga olas.

Se ejecuta enteramente en **GitHub Actions**: sin servidor, sin consola, sin
instalar nada en tu ordenador.

---

## 🌊 Qué evalúa y por qué (lo importante)

Para surf, **la altura de ola por sí sola engaña**. Una ola de 1 m puede ser
una buena sesión o un mar inservible, según de dónde venga, qué viento haya y
si hay luz para verla. Por eso este monitor mira **cinco condiciones a la vez**:

1. **Altura total ≥ 0,8 m** — que haya ola.
2. **Periodo ≥ 4 s** — que la ola tenga energía. En el Mediterráneo el periodo
   es corto de por sí (3-5 s habitual); el listón está calibrado para eso.
3. **Viento ≤ 20 km/h** — con más viento el mar se pica y la sesión se
   estropea, por muy grande que sea la ola.
4. **El oleaje de viento no aplasta al swell** — distingue el mar de fondo
   ordenado (surfeable) del mar picado de viento local (no surfeable).
5. **Hay luz solar** — calculado con el orto y el ocaso reales de cada día,
   con un margen de 30 min a cada lado. No se puede surfear de noche.

Además, solo se consideran franjas **a partir de ahora + 3 horas**: no tiene
sentido avisarte de una ventana que empieza en 30 minutos si no te da tiempo a
coger el coche y llegar.

Si hay **3 horas consecutivas** que cumplen las cinco condiciones, el spot
tiene una ventana, y recibes un mensaje.

---

## ⭐ El sistema de estrellas

Cada ventana se puntúa de **1 a 5 estrellas**, calibrado **para el
Mediterráneo**: 5 estrellas no es un día de océano, es un día notable *para
esta costa*. La nota suma puntos de cuatro factores (máximo teórico 5,5):

| Factor | Puntos | Detalle |
|--------|--------|---------|
| **Tamaño** | 0 – 2,0 | ≥1,2 m: +2 · ≥1,0 m: +1,5 · ≥0,8 m: +1 · resto: +0,5 |
| **Periodo del swell** | 0 – 1,5 | ≥6 s: +1,5 · ≥5 s: +1 · ≥4 s: +0,5 |
| **Viento** | 0 – 1,5 | offshore +1 · cross-off +0,6 · cross-on +0,3 · **onshore +0** · bonus +0,5 si <12 km/h |
| **Consenso de modelos** | 0 – 0,5 | 4 modelos coinciden +0,5 · 3 +0,4 · 2 +0,25 · 1 +0 |

El total se mapea: ≥5,0 → 5★, ≥3,5 → 4★, ≥2,5 → 3★, ≥1,5 → 2★, resto → 1★.

Decisiones de diseño:
- **Viento onshore penaliza a cero** (criterio duro): el viento del mar deshace
  la ola, así que hunde la nota aunque haya buen tamaño.
- **5 estrellas es raro y especial**: además de ≥5,0 puntos, exige tamaño real
  (≥1,0 m). Un día pequeño, por perfecto que esté el resto, tope en 4★.
- **El tamaño pequeño no es excluyente**: un 0,8 m con offshore impecable puede
  llegar a 4★.
- El veredicto-titular (Epic / Great / Good / Rideable / Marginal) se deriva de
  las estrellas.

---

## 🎯 Cuatro modelos y ponderación por fiabilidad

El monitor consulta **cuatro modelos de oleaje** de tres casas independientes.
Cuantos más coincidan, más fiable la previsión:

| Modelo | Casa | Resolución | Peso |
|--------|------|-----------|------|
| **EWAM** | DWD (alemán) | 5 km (Europa) | **×2** |
| **ECMWF WAM** | ECMWF (europeo) | 9 km (global) | **×2** |
| **MFWAM** | MeteoFrance | ~8 km (global) | ×1 |
| **GWAM** | DWD (alemán) | 25 km (global) | ×1 |

**Por qué estos pesos.** EWAM tiene la mayor resolución local para esta costa y
ECMWF es la referencia mundial en fiabilidad, así que pesan el doble. MFWAM es
sólido pero sin destacar, y GWAM es la versión basta de EWAM. EWAM y GWAM
comparten origen (DWD/ICON Wave); MFWAM y ECMWF aportan opiniones realmente
independientes, que es lo que de verdad mejora el consenso.

**Cómo se combina la altura.** En vez de una media simple, se calcula una
**media ponderada** por esos pesos. Si un solo modelo se dispara (p. ej. GWAM
predice 1,5 m cuando los otros tres dicen 1,0 m), su influencia queda diluida.
En el mensaje verás el **rango envolvente** (mínimo–máximo entre todos los
modelos) más el **valor central ponderado** como referencia:
`Waves 1.0–1.5 m (~1.1)`. El rango te avisa de la dispersión; el `~1.1` es la
mejor estimación. Las **estrellas** usan ese valor ponderado, no el máximo, de
modo que un modelo optimista no infla la nota.

Los pesos están en el diccionario `MODEL_WEIGHTS` de `surf_monitor.py` y se
pueden recalibrar.

---

## 📍 Spots monitorizados

| Spot           | Coordenadas (mar adentro) | Orientación | Previsión visual   |
|----------------|---------------------------|-------------|--------------------|
| Castelldefels  | 41.25, 2.00               | SSE (155°)  | windguru.cz/201    |
| Masnou         | 41.474775, 2.305556       | SSE (150°)  | windguru.cz/501030 |
| Sitges         | 41.234065, 1.820438       | S (190°)    | windguru.cz/48885  |

La **orientación** (hacia dónde mira el mar abierto) sirve para clasificar el
viento como offshore/onshore. Los spots se definen en la lista `SPOTS` de
`surf_monitor.py`; para añadir, quitar o cambiar uno, edita esa lista. No hacen
falta Secrets para las coordenadas.

El monitor **revisa los tres spots en cada ejecución** y envía un mensaje por
cada uno que tenga ventana. Si los tres encajan, tres mensajes; si solo uno,
un mensaje; si ninguno, ninguno (lo más habitual).

---

## 🌡 De dónde sale cada dato

El monitor combina varias fuentes de Open-Meteo, porque ningún modelo único las
tiene todas:

| Dato                          | Fuente / endpoint |
|-------------------------------|-------------------|
| Oleaje (altura, periodo, swell, dirección, wind-wave) | Marine API, modelos EWAM, GWAM, MFWAM, ECMWF |
| **Temperatura del agua**      | Marine API, sin forzar modelo (la provee **MeteoFrance**) |
| Viento (velocidad/dirección)  | Forecast API |
| Orto y ocaso                  | Forecast API (`sunrise`, `sunset`) |

> ℹ️ La temperatura del agua **no** la traen los modelos de oleaje (solo dan
> olas). Por eso se pide en una llamada aparte, sin forzar modelo, para que
> Open-Meteo use MeteoFrance. Si se pidiera junto al oleaje, devolvería vacío.

---

## ⚠️ Por qué no se hace scraping de Windguru

Windguru no permite el scraping automatizado. Pero los datos de oleaje no son
suyos: Windguru solo es una capa de visualización sobre modelos públicos
(EWAM, ECMWF, etc.). Este monitor consulta esos mismos modelos directamente en
**[Open-Meteo](https://open-meteo.com/)**, una API pública y gratuita en
formato JSON. Es la fuente original, sin intermediarios, sin navegador, sin
clave de API. Los enlaces de las alertas apuntan a Windguru solo porque su
vista gráfica es cómoda para confirmar las condiciones de un vistazo.

> **Atribución.** Datos de Open-Meteo bajo licencia CC BY 4.0, generados a
> partir de los modelos del DWD, ECMWF y MeteoFrance (vía Copernicus Marine).

---

## 📨 Cómo se ve la alerta

Recibes **un mensaje por spot** con ventana, diseñado para leerse de un vistazo
en el móvil (estilo Apple: veredicto + estrellas arriba, detalle en columnas
alineadas). Todo en inglés. Ejemplo:

> **Castelldefels**
> Great window · ★★★★☆
>
> Tomorrow · 16:00–20:00  (5h)
> ```
> Waves   0.9–1.1 m (~1.0)
> Period  5 s
> Swell   SW · 5.3 s
> Wind    15 km/h SSW ↑ cross-on
> Sea     clean
> Models  all 4 models
> ```
> Water 19° · 3/2 mm wetsuit
>
> [View full forecast](https://www.windguru.cz/201)

Claves de lectura:
- **Veredicto + estrellas** arriba para decidir en medio segundo.
- **Waves**: rango entre modelos y, entre paréntesis, el central ponderado.
- **Swell**: dirección de donde viene el groundswell y su periodo propio
  (distinto del periodo de la ola total, que va en *Period*).
- **Wind**: velocidad, dirección, flecha hacia donde sopla y clasificación
  relativa a la playa (offshore / cross-off / cross-on / onshore).
- **Models**: cuántos modelos respaldan la ventana (señal de confianza).

Si hay varias ventanas, se agrupan por día (Today / Tomorrow / Wed 04/06), cada
una con sus estrellas, y el veredicto global toma la mejor.

---

## 🔁 Sin avisos repetidos

El monitor corre cada 6 horas, así que una misma ventana podría detectarse en
varias ejecuciones seguidas. Para no recibir el mismo aviso cuatro veces, el
monitor **recuerda lo que ya ha notificado**.

Guarda por spot una "firma" de sus ventanas (día, horario y estrellas de cada
una) en un fichero `.surf_state.json`, que GitHub Actions conserva entre
ejecuciones mediante su caché. La lógica:

- Si un spot tiene una ventana **ya avisada y sin cambios**, no repite el aviso.
- Si aparece una ventana nueva, cambia el horario o cambia la calidad (sube o
  baja de estrellas), la firma cambia y **sí vuelve a avisar**, con la info
  actualizada.
- Si un spot deja de tener ventanas, se olvida su firma, de modo que un futuro
  repunte vuelva a avisar.

Notas:
- La **primera ejecución** tras desplegar no tiene estado previo (lo verás en
  el log: "No hay estado previo"), así que avisará de todo lo que encuentre. A
  partir de la segunda ya filtra duplicados.
- Si el monitor pasara **más de 7 días sin ejecutarse**, GitHub borraría la
  caché y podría repetir un aviso. Con ejecuciones cada 6 h no ocurre en la
  práctica.
- Para forzar el envío siempre (al probar), pon `ALWAYS_NOTIFY: "1"` en el
  workflow.

---

## 🕐 Horas en local

Open-Meteo devuelve las horas en la zona configurada (`Europe/Madrid`) pero sin
marca de zona horaria, mientras que el runner de GitHub Actions trabaja en UTC.
El monitor calcula "ahora" explícitamente en hora de Madrid para que la ventana
de "+3 h" y las etiquetas Today/Tomorrow sean correctas, sin desfases por el
cambio de hora ni por la zona del servidor. Si cambias `TIMEZONE`, todo el
cálculo se ajusta a esa zona.

---

## 🧴 Recomendación de neopreno

Según la temperatura del agua, para una sesión de 2-3 h (exposición larga, por
lo que se abriga un punto más que para un baño corto):

| Agua        | Recomendación |
|-------------|---------------|
| ≥ 24 °C     | rashguard or no wetsuit |
| 22-23 °C    | 2 mm shorty |
| 19-21 °C    | 3/2 mm wetsuit |
| 16-18 °C    | 4/3 mm + boots |
| 13-15 °C    | 5/4 mm, boots & hood |
| < 13 °C     | 5/4 mm with hood, gloves & boots |

> El frío es personal: si eres friolero, sube un escalón. Los rangos están en
> la función `wetsuit_recommendation` del código.

---

## 📁 Estructura del repositorio

```
.
├── .github/
│   └── workflows/
│       └── surf-monitor.yml   # El "cron" de GitHub Actions
├── surf_monitor.py            # Script principal (spots, modelos, lógica)
├── requirements.txt           # Una sola dependencia: requests
├── .gitignore
└── README.md                  # Este archivo
```

> El fichero `.surf_state.json` (anti-duplicados) lo crea el propio monitor en
> tiempo de ejecución y lo gestiona la caché de GitHub Actions. No hay que
> crearlo ni subirlo: está ignorado en `.gitignore`.

---

## 🧭 Montaje paso a paso

Todo desde el navegador, sin instalar nada.

### 1) Crear el bot de Telegram

Desde [Telegram Web](https://web.telegram.org):
1. Busca **@BotFather**, ábrelo y envía `/newbot`. Te pedirá un nombre y un
   usuario terminado en `bot`.
2. BotFather te devuelve un **token** tipo `7654321098:AAHk3l...`.
3. Para tu `chat_id`: envía cualquier mensaje a tu bot y abre en el navegador
   `https://api.telegram.org/bot<TU_TOKEN>/getUpdates`. Busca
   `"chat":{"id":123456789` → ese número es tu `chat_id`.

### 2) Crear el repositorio y subir los archivos

1. En GitHub, **New repository**, nombre (p. ej. `surf-monitor-barcelona`),
   **Private**, créalo.
2. Sube `surf_monitor.py`, `requirements.txt`, `.gitignore` y `README.md` con
   **uploading an existing file**.
3. Para el workflow: **Add file → Create new file**, nombre
   `.github/workflows/surf-monitor.yml` (las barras crean las carpetas), pega
   el contenido **una sola vez** y confirma.

> ⚠️ Si al guardar el workflow ves un error tipo *"'concurrency' is already
> defined"* o *"'jobs' is already defined"*, es que el contenido quedó pegado
> dos veces. Vacía el archivo entero (Ctrl+A, borrar) y pega una sola vez.

### 3) Guardar credenciales como Secrets

**Settings → Secrets and variables → Actions → New repository secret**. Crea
estos **dos**:

| Name (exacto)         | Secret (valor)                |
|-----------------------|-------------------------------|
| `TELEGRAM_BOT_TOKEN`  | El token que te dio BotFather |
| `TELEGRAM_CHAT_ID`    | El número de tu chat o grupo  |

⚠️ Los nombres deben escribirse exactamente así, en mayúsculas.

### 4) Primera ejecución manual (prueba)

1. Pestaña **Actions** → **Surf Monitor Barcelona** → **Run workflow**.
2. Abre la ejecución para ver los logs. Verás cómo evalúa los tres spots y, por
   cada uno, las consultas a los cuatro modelos, la temperatura y el viento.

"0 mensajes enviados" es **lo normal** la mayoría de los días. Cuando haya
ventanas, recibirás un mensaje por cada spot que las tenga.

> 💡 **Para probar Telegram:** baja temporalmente los listones en el workflow
> (`WAVE_THRESHOLD: "0.1"`, `PERIOD_THRESHOLD: "0.1"`, `WIND_MAX_KMH: "200"`).
> Disparará alertas casi seguro. **Acuérdate de revertir los valores.**

---

## ⚙️ Configuración

Los umbrales viven en el bloque `env:` del workflow. Los spots y los pesos de
los modelos, en `surf_monitor.py`.

| Variable              | Defecto | Qué hace |
|-----------------------|---------|----------|
| `WAVE_THRESHOLD`      | `0.8`   | Altura total mínima de ola (m). |
| `PERIOD_THRESHOLD`    | `4.0`   | Periodo mínimo de la ola (s). |
| `WIND_MAX_KMH`        | `20`    | Viento máximo; por encima, franja descartada. |
| `WIND_WAVE_DOMINANCE` | `1.5`   | Si el wind-wave supera al swell por más de este factor, es "mar picado" y se descarta. |
| `DAYLIGHT_MARGIN_MIN` | `30`    | Minutos de margen tras el orto y antes del ocaso. |
| `LEAD_TIME_HOURS`     | `3`     | Antelación mínima: solo ventanas que empiezan dentro de al menos estas horas. |
| `CONSECUTIVE_SLOTS`   | `3`     | Horas consecutivas surfeables para disparar la alerta. |
| `TIMEZONE`            | `Europe/Madrid` | Zona horaria. |
| `LOG_LEVEL`           | `INFO`  | `DEBUG` para ver, hora a hora, por qué cada franja es o no surfeable. |

**Más o menos estricto:** sube `WAVE_THRESHOLD` o `PERIOD_THRESHOLD` para menos
avisos, o baja `WIND_MAX_KMH` para exigir mar más limpio.

**Añadir un spot:** añade un `Spot(name=, latitude=, longitude=, forecast_url=,
facing_deg=)` a la lista `SPOTS`. Usa coordenadas mar adentro y estima la
orientación de la playa.

**Recalibrar la fiabilidad de los modelos:** edita `MODEL_WEIGHTS`.

---

## 🔬 Cómo funciona (resumen técnico)

Para **cada spot**:

1. **Forecast API** → viento horario + orto/ocaso diarios.
2. **Marine API sin forzar modelo** → temperatura del agua (MeteoFrance).
3. **Marine API por cada uno de los 4 modelos** → altura, periodo, dirección,
   swell (altura, periodo, dirección) y wind-wave, con `cell_selection=sea`.
4. **Cruce:** cada franja de oleaje se empareja con su viento, su temperatura y
   se marca diurna/nocturna, formando objetos `SurfSlot`.
5. **Filtrado temporal:** solo franjas desde ahora + `LEAD_TIME_HOURS`, hacia
   delante hasta el final de los datos (~4 días).
6. **Evaluación:** cada franja se marca surfeable o no (5 condiciones). Se
   buscan **todas** las rachas de `CONSECUTIVE_SLOTS` horas consecutivas (la
   noche resetea el contador).
7. **Fusión:** las rachas de los distintos modelos que se solapan en el tiempo
   se combinan en una sola ventana, registrando qué modelos coinciden y la
   altura de cada uno (para la media ponderada).
8. **Puntuación y envío:** se calculan las estrellas (con altura ponderada) y
   se envía un mensaje por spot con todas sus ventanas, la temperatura, el
   neopreno y el enlace.

**Robustez de red:** reintentos con back-off exponencial; si Open-Meteo
rechaza una petición (HTTP 400) muestra el motivo exacto.

**Tolerancia a fallos:** si falla la Forecast API o la de temperatura, el spot
sigue (no penaliza por falta de viento, luz o temperatura). Si falla un modelo
de oleaje, los demás se evalúan igual. Si falla un spot entero, los otros
continúan.

---

## ⏱ Sobre el tiempo de ejecución y el orden de los mensajes

Los spots se procesan **en serie**, y cada uno hace seis llamadas a Open-Meteo
(cuatro modelos + viento + temperatura). Si alguna llamada tarda o entra en
reintentos, los mensajes de distintos spots pueden llegar espaciados (algún
minuto). No es un error: el sistema espera en lugar de fallar. Para un monitor
que corre cada 6 horas no tiene impacto práctico. Si prefieres que lleguen
juntos, una mejora futura sería agrupar todos los spots en un solo mensaje.

---

## 💸 Coste

Cero. GitHub Actions es gratuito dentro de cuota (pocos minutos por ejecución,
4 veces al día). Open-Meteo es gratuito para uso no comercial sin clave ni
registro. No hay servidor que mantener.

---

## 🧯 Solución de problemas

| Síntoma | Causa probable | Solución |
|---|---|---|
| Error al guardar el workflow: `'jobs' is already defined` | El YAML quedó pegado dos veces | Vacía el archivo entero y pega una sola vez. |
| `Open-Meteo rechazo la peticion: ...` | Parámetro mal formado o id de modelo inválido | El log muestra el motivo exacto. |
| Un modelo dice "Sin datos" para un spot | Ese modelo no cubre ese punto | Los cuatro son europeos/globales y cubren la zona; ajusta coordenadas mar adentro si persiste. El resto de modelos sigue funcionando. |
| Agua "sin dato" en la alerta | La llamada de temperatura falló o devolvió vacío | Revisa la línea `[spot/sst]` del log; suele resolverse solo o ajustando coordenadas. |
| `Swell n/a` en el mensaje | El modelo no sirvió dirección de swell para ese punto | Informativo; el resto de la ventana es válido. |
| No llega ningún mensaje | Token/chat_id mal, o no hay ventanas | Revisa Secrets y prueba bajando umbrales. "0 mensajes" suele ser normal. |
| Mensajes de spots espaciados en el tiempo | Reintentos de red en algún spot | Normal; ver sección sobre tiempo de ejecución. |
| El schedule no arranca solo | GitHub tarda en activar el primer schedule, o pausa workflows en repos inactivos ~60 días | Usa **Run workflow** y haz algún commit de vez en cuando. |

---

## 📜 Licencia

Código bajo licencia MIT. Datos de oleaje, viento, temperatura del agua y
orto/ocaso por **Open-Meteo** (CC BY 4.0), generados a partir de los modelos
del DWD (EWAM, GWAM), ECMWF (WAM) y MeteoFrance (MFWAM y SST, vía Copernicus
Marine).
