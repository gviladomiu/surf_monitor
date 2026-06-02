# 🏄 Surf Monitor — costa de Barcelona

Monitor automático de condiciones de **surf** para varios spots de la costa de
Barcelona: **Castelldefels, Masnou y Sitges**. Cada 6 horas revisa la previsión
de cada spot, evalúa si hay una ventana surfeable **a partir de las próximas
3 horas** (el tiempo que necesitas para llegar en coche), y avisa por
**Telegram** con un mensaje claro por cada spot que tenga olas.

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
tiene una ventana, y recibes un mensaje que incluye:
- Las ventanas detectadas, **agrupadas por día** y con los dos modelos
  (EWAM y GWAM) fusionados (cuando coinciden, es señal de confianza).
- La **temperatura del agua** y una **recomendación de neopreno** para una
  sesión de 2-3 h.
- Un **enlace a la previsión visual** del spot en Windguru.

> **Nota sobre estos spots.** Son spots mediterráneos de **swell débil**: el
> oleaje de fondo raramente supera los 0,8 m. Por eso el umbral de tamaño usa
> la altura *total* y no un umbral alto de swell. Los valores están calibrados
> con datos reales de la costa.

---

## 📍 Spots monitorizados

| Spot           | Coordenadas (mar adentro) | Previsión visual   |
|----------------|---------------------------|--------------------|
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
> partir de los modelos del Deutscher Wetterdienst (DWD), y temperatura del
> agua de MeteoFrance (vía Copernicus Marine).

---

## 🌡 De dónde sale cada dato

El monitor combina **tres fuentes** de Open-Meteo, porque ningún modelo único
las tiene todas:

| Dato                        | Fuente / endpoint                              |
|-----------------------------|------------------------------------------------|
| Oleaje (altura, periodo, swell, viento-ola) | Marine API, modelos DWD **EWAM** y **GWAM** |
| **Temperatura del agua**    | Marine API, sin forzar modelo (la provee **MeteoFrance**) |
| Viento (velocidad/dirección)| Forecast API |
| Orto y ocaso                | Forecast API (`sunrise`, `sunset`) |

> ℹ️ Detalle técnico importante: la temperatura del agua **no** la traen los
> modelos EWAM/GWAM (solo dan oleaje). Por eso se pide en una llamada aparte,
> sin forzar modelo, para que Open-Meteo use MeteoFrance. Si se pidiera junto
> al oleaje, devolvería siempre vacío.

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
     (las barras `/` crean las carpetas). Pega el contenido **una sola vez**
     y confirma.

> ⚠️ Si al guardar el workflow te da un error tipo *"'concurrency' is already
> defined"* o *"'jobs' is already defined"*, es que el contenido quedó pegado
> dos veces. Vacía el archivo por completo (Ctrl+A, borrar) y pega una sola vez.

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

En el log verás cómo evalúa los tres spots uno por uno. Fíjate en estas líneas
para confirmar que todo va bien:

```
--- Evaluando spot: Castelldefels ---
[Castelldefels/aux] Consultando Forecast API (viento + sol)...
[Castelldefels/aux] Viento: 96 franjas. Luz solar: 4 dias.
[Castelldefels/sst] Consultando temperatura del agua...
[Castelldefels/sst] Temperatura del agua: 96 franjas con dato.   <-- debe ser > 0
[Castelldefels/EWAM] Obtenidas 96 franjas con datos completos.
[Castelldefels/GWAM] Obtenidas 96 franjas con datos completos.
[Castelldefels/EWAM] ❌ Sin racha surfeable.
...
=== Fin. 0 spot(s) con ventana, 0 mensaje(s) enviado(s). ===
```

"0 mensajes" es **lo normal** la mayoría de los días: no hay ventanas
surfeables. Cuando las haya, recibirás un mensaje por cada spot que las tenga.

> 💡 **Para probar que Telegram funciona:** edita temporalmente el workflow y
> baja los listones, p. ej. `WAVE_THRESHOLD: "0.1"`, `PERIOD_THRESHOLD: "0.1"`
> y `WIND_MAX_KMH: "200"`. Eso disparará alertas casi seguro. **Acuérdate de
> volver a dejar los valores originales después.**

---

## 📨 Cómo se ve la alerta

Recibes **un mensaje por spot** con ventana, diseñado para leerse de un vistazo
en el móvil. Ejemplo:

> 🏄 **SURF · CASTELLDEFELS**
> 2 ventanas en 2 dias
> 🌡 Agua 19°C  ·  🧴 neopreno 3/2 mm
> ━━━━━━━━━━━━━━━━━━━
>
> 📅 **JUE 04/06**
> 🕐 16:00–20:00  (5 h)  ✅ coinciden EWAM y GWAM
>      🌊 0.9–1.1 m  ·  ⏱ 5 s  ·  💨 15 km/h SSW  ·  🟢
>
> 📅 **VIE 05/06**
> 🕐 07:00–13:00  (7 h)  · solo GWAM
>      🌊 0.9–1.2 m  ·  ⏱ 5–6 s  ·  💨 14 km/h SW  ·  🟢
>
> ━━━━━━━━━━━━━━━━━━━
> 🟢 limpio · 🟡 mixto · 🟠 movido
> 🔗 Ver previsión completa

Claves de lectura:
- **Agrupado por día**, porque lo natural es pensar "¿qué hago el jueves?".
- **Los dos modelos fusionados:** cuando EWAM y GWAM coinciden en una ventana,
  aparece "✅ coinciden EWAM y GWAM" (más confianza para ir). Si solo lo ve
  uno, aparece "· solo EWAM/GWAM".
- **Iconos como anclas:** 🌊 tamaño · ⏱ periodo · 💨 viento · semáforo de
  calidad (🟢 limpio, 🟡 mixto, 🟠 movido).

---

## 🧴 Recomendación de neopreno

Según la temperatura del agua, para una sesión de 2-3 h (exposición larga, por
lo que se abriga un punto más que para un baño corto):

| Agua        | Recomendación |
|-------------|---------------|
| ≥ 24 °C     | Lycra o sin neopreno |
| 22-23 °C    | Shorty 2 mm |
| 19-21 °C    | Neopreno 3/2 mm |
| 16-18 °C    | Neopreno 4/3 mm + escarpines |
| 13-15 °C    | Neopreno 5/4 mm, escarpines y capucha |
| < 13 °C     | 5/4 mm con capucha, guantes y escarpines |

> El frío es personal: si eres friolero, sube un escalón; si aguantas bien,
> baja uno. Los rangos están en la función `wetsuit_recommendation` del código.

---

## ⚙️ Configuración

Los umbrales viven en el bloque `env:` del archivo
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

1. **Una llamada a la Forecast API** para viento horario y orto/ocaso diarios.
2. **Una llamada a la Marine API sin forzar modelo** para la temperatura del
   agua (la provee MeteoFrance).
3. **Una llamada a la Marine API por cada modelo** de oleaje (EWAM, GWAM),
   pidiendo altura, periodo, dirección, swell y wind wave, con
   `cell_selection=sea` para forzar una celda de mar.
4. **Cruce de datos.** Cada franja horaria de oleaje se empareja con su viento,
   su temperatura del agua y se marca como diurna o nocturna, formando objetos
   `SurfSlot`.
5. **Filtrado temporal.** Se conservan solo las franjas a partir de ahora +
   `LEAD_TIME_HOURS`, hacia delante hasta el final de los datos (~4 días).
6. **Evaluación.** Cada franja se marca como surfeable o no según las 5
   condiciones. Se buscan **todas** las rachas de `CONSECUTIVE_SLOTS` franjas
   consecutivas (la noche resetea el contador).
7. **Fusión y notificación.** Las rachas de ambos modelos que se solapan en el
   tiempo se fusionan (marcando si coinciden), se agrupan por día, y se envía
   un único mensaje por spot con la temperatura, el neopreno y el enlace.

**Tolerancia a fallos:** si la Forecast API o la llamada de temperatura fallan,
el spot sigue evaluándose (no penaliza por falta de viento, luz o temperatura).
Si un modelo de oleaje falla, el otro se evalúa igual. Si un spot entero falla,
los demás se evalúan con normalidad.

---

## 💸 Coste

Cero. GitHub Actions es gratuito dentro de cuota (este workflow consume pocos
minutos por ejecución, 4 veces al día; ahora hace más llamadas al evaluar tres
spots con varias fuentes, pero sigue siendo muy poco). Open-Meteo es gratuito
para uso no comercial sin clave ni registro. No hay servidor que mantener.

---

## 🧯 Solución de problemas

| Síntoma | Causa probable | Solución |
|---|---|---|
| Error al guardar el workflow: `'jobs' is already defined` | El contenido del YAML quedó pegado dos veces | Vacía el archivo entero y pega una sola vez. |
| `Open-Meteo rechazo la peticion: ...` | Un parámetro mal formado o id de modelo inválido | El log muestra el motivo exacto que da la API. |
| `[spot/sst] Temperatura del agua: 0 franjas con dato` | MeteoFrance no cubre ese punto exacto | Ajusta las coordenadas del spot un poco más mar adentro. |
| Agua "sin dato" en la alerta | La llamada de temperatura falló o devolvió vacío | Revisa la línea `[spot/sst]` del log; suele resolverse solo o ajustando coordenadas. |
| Un modelo dice "Sin datos" para un spot | Ese modelo no cubre esas coordenadas | EWAM solo cubre Europa; GWAM es global. Ajusta coordenadas mar adentro. |
| `[spot/aux] No se pudieron obtener datos auxiliares` | La Forecast API falló | No es crítico: el spot sigue, pero sin filtrar por viento ni luz esa vez. |
| No llega ningún mensaje | Token/chat_id mal, o no hay ventanas | Revisa Secrets y prueba el truco de bajar umbrales. "0 mensajes" suele ser normal. |
| El schedule no arranca solo | GitHub tarda en activar el primer schedule, o pausa workflows en repos inactivos ~60 días | Usa **Run workflow** y haz algún commit de vez en cuando. |

---

## 📜 Licencia

Código bajo licencia MIT. Datos de oleaje, viento y orto/ocaso por
**Open-Meteo** (CC BY 4.0), generados a partir de los modelos del Deutscher
Wetterdienst (DWD); temperatura del agua de **MeteoFrance** vía Copernicus
Marine.
