# 🏄 Surf Monitor — costa de Barcelona

Monitor automático de condiciones de **surf** para varios spots de la costa de
Barcelona: **Castelldefels, Masnou y Sitges**. Cada 6 horas revisa la previsión
de cada spot, evalúa si hay una ventana surfeable **a partir de las próximas
3 horas** (el tiempo que necesitas para llegar en coche), y avisa por
**Telegram** con un mensaje por cada spot que tenga olas.

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

Además, solo se consideran franjas **a partir de ahora + 3 horas** (el tiempo
de desplazamiento al spot). No tiene sentido avisarte de una ventana que
empieza en 30 minutos si no te da tiempo a llegar.

Si hay **3 horas consecutivas** que cumplen las cinco condiciones, el spot
tiene una ventana, y recibes un mensaje. El mensaje incluye:
- Las ventanas detectadas por **cada modelo** (EWAM y GWAM), combinadas en
  un solo mensaje por spot.
- La **temperatura del agua** y una **recomendación de neopreno** para una
  sesión de 2-3 h.
- Un **enlace a la previsión visual** del spot en Windguru.

> **Nota sobre estos spots.** Son spots mediterráneos de **swell débil**: el
> oleaje de fondo raramente supera los 0,8 m. Por eso el umbral de tamaño usa
> la altura *total* y no un umbral alto de swell. Los valores están calibrados
> con datos reales de la costa.

---

## 📍 Spots monitorizados

| Spot           | Coordenadas (mar adentro) | Previsión visual |
|----------------|---------------------------|------------------|
| Castelldefels  | 41.25, 2.00               | windguru.cz/201    |
| Masnou         | 41.474775, 2.305556       | windguru.cz/501030 |
| Sitges         | 41.234065, 1.820438       | windguru.cz/48885  |

Los spots se definen en la lista `SPOTS` del archivo `surf_monitor.py`. Para
añadir, quitar o cambiar un spot, edita esa lista (nombre, latitud, longitud y
URL de Windguru). No hacen falta Secrets para las coordenadas.

---

## ⚠️ Por qué no se hace scraping de Windguru

Windguru no permite el scraping automatizado. Pero los datos de oleaje no son
suyos: Windguru solo es una capa de visualización sobre modelos públicos. El
modelo de oleaje del servicio meteorológico alemán (DWD) se llama **ICON Wave**
y se publica en dos productos: **EWAM** (Europa, alta resolución 5 km) y
**GWAM** (global, 25 km).

Este monitor consulta esos mismos modelos del DWD directamente en
**[Open-Meteo](https://open-meteo.com/)**, una API pública y gratuita en
formato JSON. Es la fuente original, sin intermediarios, sin navegador, sin
clave de API. Los enlaces de las alertas apuntan a Windguru solo porque su
vista gráfica es cómoda para confirmar las condiciones de un vistazo.

> **Atribución.** Datos de Open-Meteo bajo licencia CC BY 4.0, generados a
> partir de los modelos del Deutscher Wetterdienst (DWD).

---

## 📁 Estructura del repositorio

```
.
├── .github/
│   └── workflows/
│       └── surf-monitor.yml   # El "cron" de GitHub Actions
├── surf_monitor.py            # Script principal (incluye la lista de spots)
├── requirements.txt           # Una sola dependencia: requests
├── .gitignore
└── README.md                  # Este archivo
```

---

## 🧭 Resumen del montaje

Todo desde el navegador, sin instalar nada:

1. Crear el bot de Telegram y obtener `token` + `chat_id`.
2. Crear un repositorio **privado** en GitHub y subir estos archivos.
3. Guardar `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` como *Secrets*.
4. Lanzar el workflow a mano una vez para comprobar que funciona.

> Las coordenadas ya no son Secrets: van en la lista `SPOTS` del código.

---

## 1️⃣ Crear el bot de Telegram

Desde [Telegram Web](https://web.telegram.org), sin tocar el móvil:

**Crear el bot:**
1. Busca **@BotFather** (marca de verificación azul) y ábrelo.
2. Envía `/newbot`. Te pedirá un nombre y un nombre de usuario terminado
   en `bot`.
3. BotFather te devuelve un **token** tipo `7654321098:AAHk3l...`.

**Obtener tu `chat_id`:**
1. Busca tu bot recién creado y envíale cualquier mensaje (`hola`).
2. En el navegador, abre (sustituyendo tu token):
   ```
   https://api.telegram.org/bot<TU_TOKEN>/getUpdates
   ```
3. En el JSON, busca `"chat":{"id":123456789` → ese número es tu `chat_id`.

---

## 2️⃣ Crear el repositorio y subir los archivos

1. En GitHub, **New repository**, ponle nombre (p. ej.
   `surf-monitor-barcelona`), márcalo como **Private** y créalo.
2. Sube los archivos:
   - Arrastra `surf_monitor.py`, `requirements.txt`, `.gitignore`
     y `README.md` con la opción **uploading an existing file**.
   - Para el workflow, usa **Add file → Create new file** y escribe como
     nombre la ruta completa `.github/workflows/surf-monitor.yml`
     (las barras `/` crean las carpetas). Pega el contenido y confirma.

---

## 3️⃣ Guardar credenciales como Secrets

En tu repositorio: **Settings → Secrets and variables → Actions →
New repository secret**. Crea estos **dos** secretos:

| Name (exacto)         | Secret (valor)                |
|-----------------------|-------------------------------|
| `TELEGRAM_BOT_TOKEN`  | El token que te dio BotFather |
| `TELEGRAM_CHAT_ID`    | El número de tu chat o grupo  |

⚠️ Los nombres deben escribirse **exactamente así**, en mayúsculas.

---

## 4️⃣ Primera ejecución manual (prueba)

1. Ve a la pestaña **Actions** de tu repositorio.
2. Pulsa **Surf Monitor Barcelona** en la lista de la izquierda.
3. Pulsa **Run workflow → Run workflow**.
4. Abre la ejecución para ver los logs en tiempo real.

Verás en el log cómo evalúa los tres spots uno por uno. "0 mensajes enviados"
es **lo normal** la mayoría de los días: no hay ventanas surfeables. Cuando las
haya, recibirás un mensaje por cada spot que las tenga.

> 💡 **Para probar que Telegram funciona:** edita temporalmente el workflow y
> baja los listones, p. ej. `WAVE_THRESHOLD: "0.1"`, `PERIOD_THRESHOLD: "0.1"`
> y `WIND_MAX_KMH: "200"`. Eso disparará alertas casi seguro. **Acuérdate de
> volver a dejar los valores originales después.**

---

## 📨 Cómo se ve la alerta

Recibes **un mensaje por spot** con ventana. Ejemplo:

> 🏄 **Ventana de surf detectada**
>
> Spot: **Castelldefels**
> Agua: 19C
> Neopreno (sesión 2-3 h): agua ~19C: neopreno 3/2 mm
>
> Criterio: olas >= 0.8 m, periodo >= 4.0 s, viento < 20 km/h, con luz, a partir de +3 h.
>
> **Modelo EWAM** — 1 ventana:
>   (4 h)
>   Franja: 15:00 - 18:00 del 16/05
>   Altura: 0.95 - 0.95 m
>   Periodo: 4.8 - 4.8 s
>   Dirección de la ola: viene del SSW
>   Calidad: mar limpio (predomina el swell de fondo)
>   Viento: 12 km/h del WNW
>
> **Modelo GWAM** — 1 ventana:
>   (3 h)
>   Franja: 16:00 - 18:00 del 16/05
>   ...
>
> 🔗 Ver previsión completa: https://www.windguru.cz/201
>
> Fuente: Open-Meteo (modelos EWAM y GWAM, DWD)

Ver los dos modelos juntos te permite contrastar: si EWAM y GWAM coinciden,
más confianza para ir; si discrepan, también es información útil.

---

## 🧴 Recomendación de neopreno

Según la temperatura del agua, para una sesión de 2-3 h (exposición larga, por
lo que se abriga un punto más que para un baño corto):

| Agua        | Recomendación |
|-------------|---------------|
| ≥ 24 °C     | Lycra o sin neopreno (a lo sumo top 1-2 mm) |
| 22-23 °C    | Shorty 2 mm o neopreno corto |
| 19-21 °C    | Neopreno 3/2 mm |
| 16-18 °C    | Neopreno 4/3 mm (valora escarpines) |
| 13-15 °C    | Neopreno 5/4 mm + escarpines; guantes y capucha si aguantas 2-3 h |
| < 13 °C     | 5/4 mm o más, con capucha, guantes y escarpines |

---

## ⚙️ Configuración

Toda la configuración de umbrales vive en el bloque `env:` del archivo
`.github/workflows/surf-monitor.yml`. Los spots, en la lista `SPOTS` de
`surf_monitor.py`.

| Variable              | Valor por defecto | Qué hace |
|-----------------------|-------------------|----------|
| `WAVE_THRESHOLD`      | `0.8`             | Altura total mínima de ola, en metros. |
| `PERIOD_THRESHOLD`    | `4.0`             | Periodo mínimo de la ola, en segundos. |
| `WIND_MAX_KMH`        | `20`              | Viento máximo. Por encima, franja descartada. |
| `WIND_WAVE_DOMINANCE` | `1.5`             | Si el oleaje de viento supera al swell por más de este factor, es "mar picado" y se descarta. |
| `DAYLIGHT_MARGIN_MIN` | `30`              | Minutos de margen tras el orto y antes del ocaso. |
| `LEAD_TIME_HOURS`     | `3`               | Antelación mínima: solo mira ventanas que empiezan dentro de al menos estas horas. |
| `CONSECUTIVE_SLOTS`   | `3`               | Horas consecutivas surfeables para disparar la alerta. |
| `TIMEZONE`            | `Europe/Madrid`   | Zona horaria para interpretar las fechas. |
| `LOG_LEVEL`           | `INFO`            | Pon `DEBUG` para ver, hora a hora, por qué cada franja es o no surfeable. |

**Para hacerlo más o menos estricto:** sube `WAVE_THRESHOLD` o `PERIOD_THRESHOLD`
para menos avisos (solo días mejores), o baja `WIND_MAX_KMH` para exigir mar
más limpio. Al revés para recibir más avisos.

**Añadir un spot:** edita la lista `SPOTS` en `surf_monitor.py` añadiendo un
`Spot(name=..., latitude=..., longitude=..., forecast_url=...)`. Usa
coordenadas ligeramente mar adentro.

**Cambiar de modelos:** el diccionario `MODELS` en `surf_monitor.py` mapea el
nombre que verás con el identificador de Open-Meteo. Otros válidos:
`ecmwf_wam`, `meteofrance_wave`.

---

## 🔬 Cómo funciona (resumen técnico)

Para **cada spot** de la lista:

1. **Una llamada a la Forecast API** para datos auxiliares: viento horario y
   orto/ocaso diarios.
2. **Una llamada a la Marine API por cada modelo** (EWAM, GWAM), pidiendo
   altura, periodo, dirección, swell, wind wave y **temperatura del agua**,
   con `cell_selection=sea` para forzar una celda de mar.
3. **Cruce de datos.** Cada franja horaria se empareja con su viento y se marca
   como diurna o nocturna, formando objetos `SurfSlot`.
4. **Filtrado temporal.** Se conservan solo las franjas a partir de ahora +
   `LEAD_TIME_HOURS`, hacia delante hasta el final de los datos (~4 días).
5. **Evaluación.** Cada franja se marca como surfeable o no según las 5
   condiciones. Se buscan **todas** las rachas de `CONSECUTIVE_SLOTS` franjas
   consecutivas (la noche resetea el contador).
6. **Notificación.** Si el spot tiene al menos una racha en algún modelo, se
   envía un único mensaje con todos los modelos combinados, la temperatura del
   agua, la recomendación de neopreno y el enlace a la previsión visual.

**Tolerancia a fallos:** si la Forecast API auxiliar falla, el spot sigue
evaluándose (no penaliza por falta de viento ni de sol). Si un modelo de oleaje
falla, el otro se evalúa igual. Si un spot entero falla, los demás se evalúan
con normalidad.

---

## 💸 Coste

Cero. GitHub Actions es gratuito dentro de cuota (este workflow consume pocos
minutos por ejecución, 4 veces al día, aunque ahora hace más llamadas al
evaluar tres spots). Open-Meteo es gratuito para uso no comercial sin clave ni
registro. No hay servidor que mantener.

---

## 🧯 Solución de problemas

| Síntoma | Causa probable | Solución |
|---|---|---|
| `Open-Meteo rechazo la peticion: ...` | Un parámetro mal formado o id de modelo inválido | El log muestra el motivo exacto que da la API. |
| Un modelo dice "Sin datos" para un spot | Ese modelo no cubre esas coordenadas | EWAM solo cubre Europa; GWAM es global. Ajusta las coordenadas del spot un poco más mar adentro. |
| `[spot/aux] No se pudieron obtener datos auxiliares` | La Forecast API falló | No es crítico: el spot sigue, pero sin filtrar por viento ni luz esa vez. |
| No llega ningún mensaje | Token/chat_id mal, o no hay ventanas | Revisa Secrets y prueba el truco de bajar umbrales. "0 mensajes" suele ser normal. |
| Agua "sin dato" en la alerta | El modelo no devolvió temperatura para ese punto | Suele resolverse solo en la siguiente ejecución; si persiste, ajusta las coordenadas del spot. |
| El schedule no arranca solo | GitHub tarda en activar el primer schedule, o pausa workflows en repos inactivos ~60 días | Usa **Run workflow** y haz algún commit de vez en cuando. |

---

## 📜 Licencia

Código bajo licencia MIT. Datos de oleaje, viento, temperatura del agua y
orto/ocaso por **Open-Meteo** (CC BY 4.0), generados a partir de los modelos
del Deutscher Wetterdienst (DWD).
