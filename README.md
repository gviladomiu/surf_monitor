# 🏄 Surf Monitor — Castelldefels

Monitor automático de condiciones de **surf** para Castelldefels (Barcelona).
Cada 6 horas revisa la previsión, evalúa si **pasado mañana** o el **día
siguiente** habrá una ventana surfeable, y avisa por **Telegram** con un enlace
directo a la previsión visual.

Se ejecuta enteramente en **GitHub Actions**: sin servidor, sin consola, sin
instalar nada en tu ordenador.

---

## 🌊 Qué evalúa y por qué (lo importante)

Para surf, **la altura de ola por sí sola engaña**. Una ola de 1 m puede ser
una buena sesión o un mar inservible, según de dónde venga, qué viento haya y
si hay luz para verla. Por eso este monitor no mira solo el tamaño, sino
**cinco condiciones a la vez**:

1. **Altura total ≥ 0,8 m** — que haya ola.
2. **Periodo ≥ 4 s** — que la ola tenga energía. En el Mediterráneo el periodo
   es corto de por sí (3-5 s habitual), así que el listón está calibrado para
   esa realidad, no para un océano.
3. **Viento ≤ 20 km/h** — con más viento el mar se pica y la sesión se
   estropea, por muy grande que sea la ola.
4. **El oleaje de viento no aplasta al swell** — distingue el mar de fondo
   ordenado (surfeable) del mar picado de viento local (no surfeable).
5. **Hay luz solar** — calculado con el orto y el ocaso reales de cada día,
   con un margen de 30 minutos a cada lado para descartar la primera media
   hora del amanecer y la última del atardecer (luz rasante y débil). No se
   puede surfear de noche, así que no tiene sentido alertar de rachas
   nocturnas, por muy buenas que sean.

Si hay **3 horas consecutivas** que cumplen las cinco condiciones, salta la
alerta. El mensaje de Telegram incluye altura, periodo, dirección, calidad del
mar (limpio / movido), viento, y un enlace a la previsión visual completa.

> **Nota sobre Castelldefels.** Es un spot mediterráneo de **swell débil**: el
> oleaje de fondo raramente supera los 0,8 m. Por eso el umbral de tamaño usa
> la altura *total* y no un umbral alto de swell (que dejaría el monitor
> prácticamente mudo). Los valores están calibrados con datos reales del spot.

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
clave de API. Eso sí: el enlace que llega en la alerta apunta a Windguru,
porque su vista gráfica es cómoda para confirmar las condiciones de un vistazo
antes de coger la tabla.

> **Atribución.** Datos de Open-Meteo bajo licencia CC BY 4.0, generados a
> partir de los modelos del Deutscher Wetterdienst (DWD).

---

## 📁 Estructura del repositorio

```
.
├── .github/
│   └── workflows/
│       └── surf-monitor.yml   # El "cron" de GitHub Actions
├── surf_monitor.py            # Script principal
├── requirements.txt           # Una sola dependencia: requests
├── .gitignore
└── README.md                  # Este archivo
```

---

## 🧭 Resumen del montaje

Todo desde el navegador, sin instalar nada:

1. Crear el bot de Telegram y obtener `token` + `chat_id`.
2. Crear un repositorio **privado** en GitHub y subir estos archivos.
3. Guardar las credenciales y coordenadas como *Secrets* del repositorio.
4. Lanzar el workflow a mano una vez para comprobar que funciona.

---

## 1️⃣ Coordenadas del spot

Open-Meteo trabaja con **latitud y longitud**. Para Castelldefels usamos un
punto **ligeramente mar adentro**, no justo en la orilla. Estos son los valores
definitivos para los Secrets:

| Secret           | Valor   |
|------------------|---------|
| `SPOT_LATITUDE`  | `41.25` |
| `SPOT_LONGITUDE` | `2.00`  |

> 💡 **Por qué mar adentro:** los modelos de oleaje funcionan sobre celdas de
> mar. Si el punto cae en la orilla, el modelo puede devolver datos pobres o
> nulos. El script pide `cell_selection=sea` para forzar una celda de mar, y
> registra en el log a qué coordenadas ha respondido realmente Open-Meteo
> (puede moverlas unos km para encajar en una celda válida; es normal).

---

## 2️⃣ Crear el bot de Telegram

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

## 3️⃣ Crear el repositorio y subir los archivos

1. En GitHub, **New repository**, ponle nombre (p. ej.
   `surf-monitor-castelldefels`), márcalo como **Private** y créalo.
2. Sube los archivos:
   - Arrastra `surf_monitor.py`, `requirements.txt`, `.gitignore`
     y `README.md` con la opción **uploading an existing file**.
   - Para el workflow, usa **Add file → Create new file** y escribe como
     nombre la ruta completa `.github/workflows/surf-monitor.yml`
     (las barras `/` crean las carpetas). Pega el contenido y confirma.

---

## 4️⃣ Guardar credenciales y coordenadas como Secrets

En tu repositorio: **Settings → Secrets and variables → Actions →
New repository secret**. Crea estos **cuatro** secretos:

| Name (exacto)         | Secret (valor)                          |
|-----------------------|-----------------------------------------|
| `TELEGRAM_BOT_TOKEN`  | El token que te dio BotFather           |
| `TELEGRAM_CHAT_ID`    | El número de tu chat o grupo            |
| `SPOT_LATITUDE`       | `41.25`                                 |
| `SPOT_LONGITUDE`      | `2.00`                                  |

⚠️ Los nombres deben escribirse **exactamente así**, en mayúsculas.

---

## 5️⃣ Primera ejecución manual (prueba)

1. Ve a la pestaña **Actions** de tu repositorio.
2. Pulsa **Surf Monitor Castelldefels** en la lista de la izquierda.
3. Pulsa **Run workflow → Run workflow**.
4. Abre la ejecución para ver los logs en tiempo real.

Si todo va bien, el log del paso "Ejecutar Surf Monitor" mostrará algo así:

```
=== Surf Monitor (Open-Meteo) — spot 'Castelldefels' ===
Modelos a evaluar: ['EWAM', 'GWAM']
[aux] Consultando Forecast API (viento + sol)...
[aux] Viento: 96 franjas obtenidas.
[aux] Luz solar: 4 dias. Ejemplo 2026-05-16 -> 07:12 a 20:38.
[EWAM] Consultando Open-Meteo Marine (modelo 'ewam')...
[EWAM] Open-Meteo respondio para lat=41.2 lon=2.0 (pedido: 41.25, 2.00).
[EWAM] Obtenidas 96 franjas con datos completos.
[GWAM] Consultando Open-Meteo Marine (modelo 'gwam')...
[GWAM] Obtenidas 96 franjas con datos completos.
Ventana de evaluacion: 2026-05-16 -> 2026-05-17 (pasado manana + dia siguiente)
Criterio surfeable: altura >= 0.8m Y periodo >= 4.0s Y viento <= 20km/h Y wind wave no domina Y hay luz solar (margen +/-30min); 3 franjas seguidas.
[EWAM] 48 franjas en la ventana, 0 cumplen el criterio surfeable.
[EWAM] ❌ No hay racha surfeable suficiente.
[GWAM] 48 franjas en la ventana, 0 cumplen el criterio surfeable.
[GWAM] ❌ No hay racha surfeable suficiente.
=== Ejecucion finalizada. Alertas enviadas: 0 ===
```

"Alertas enviadas: 0" es **lo normal** la mayoría de los días: significa que no
hay una ventana de surf en pasado mañana / el día siguiente. Cuando la haya,
recibirás el mensaje en Telegram.

> 💡 **Para probar que Telegram funciona:** edita temporalmente el workflow y
> baja los listones, p. ej. `WAVE_THRESHOLD: "0.1"`, `PERIOD_THRESHOLD: "0.1"`
> y `WIND_MAX_KMH: "200"`. Eso disparará la alerta casi seguro en la siguiente
> ejecución manual. **Acuérdate de volver a dejar los valores originales.**

---

## 📨 Cómo se ve la alerta

Cuando hay una ventana surfeable, recibes un mensaje así (ejemplo con datos
reales):

> 🏄 **Posible sesión de surf**
>
> Spot: Castelldefels
> Modelo: EWAM
>
> Detectadas 3 horas consecutivas surfeables:
> olas de al menos 0.8 m, periodo de al menos 4.0 s y viento por debajo de 20 km/h.
>
>   Franja: 10:00 - 12:00 del 16/05
>   Altura: 0.92 - 1.02 m
>   Periodo: 5.0 - 5.1 s
>   Dirección de la ola: viene del SW
>   Calidad: mar limpio (predomina el swell de fondo)
>   Viento: 12 km/h del WNW
>
> _El Mediterráneo tiene periodo corto; aun así estas son de las mejores
> ventanas. Confirma el viento antes de ir: offshore (de tierra) lo mejora
> mucho._
>
> 🔗 Ver previsión completa: https://www.windguru.cz/201
>
> Fuente: Open-Meteo (modelo EWAM)

Debajo del mensaje, Telegram muestra una tarjeta de vista previa clicable de
Windguru, para que puedas abrir la previsión de un toque.

Si en una misma ejecución **EWAM y GWAM** detectan una ventana, recibes dos
mensajes (uno por modelo), útil para comparar.

---

## ⚙️ Configuración

Toda la configuración (salvo los Secrets) vive en el bloque `env:` del archivo
`.github/workflows/surf-monitor.yml`. Edítalo desde la web de GitHub:

| Variable              | Valor por defecto | Qué hace |
|-----------------------|-------------------|----------|
| `SPOT_NAME`           | `Castelldefels`   | Nombre que aparece en la alerta. |
| `WAVE_THRESHOLD`      | `0.8`             | Altura total mínima de ola, en metros. |
| `PERIOD_THRESHOLD`    | `4.0`             | Periodo mínimo de la ola, en segundos. |
| `WIND_MAX_KMH`        | `20`              | Viento máximo. Por encima, franja descartada. |
| `WIND_WAVE_DOMINANCE` | `1.5`             | Si el oleaje de viento supera al swell por más de este factor, es "mar picado" y se descarta. |
| `DAYLIGHT_MARGIN_MIN` | `30`              | Minutos de margen tras el orto y antes del ocaso. Sube para exigir más luz; baja a 0 para no margen. |
| `CONSECUTIVE_SLOTS`   | `3`               | Horas consecutivas surfeables para disparar la alerta. |
| `TIMEZONE`            | `Europe/Madrid`   | Zona horaria para interpretar las fechas. |
| `LOG_LEVEL`           | `INFO`            | Pon `DEBUG` para ver, hora a hora, por qué cada franja es o no surfeable. |

Hay además una variable opcional que **no** está en el workflow por defecto
porque tiene un valor sensato fijado en el código:

| Variable             | Valor por defecto              | Qué hace |
|----------------------|--------------------------------|----------|
| `SPOT_FORECAST_URL`  | `https://www.windguru.cz/201`  | Enlace de previsión visual que aparece en la alerta. Si quieres cambiarlo, añádelo al bloque `env:`. |

**Para hacerlo más o menos estricto:** sube `WAVE_THRESHOLD` o `PERIOD_THRESHOLD`
para recibir menos avisos (solo días mejores), o baja `WIND_MAX_KMH` para exigir
mar más limpio. Al revés para recibir más avisos.

**Cambiar de modelos:** en `surf_monitor.py`, el diccionario `MODELS` mapea el
nombre que verás en la alerta con el identificador de Open-Meteo. Por defecto
`{"EWAM": "ewam", "GWAM": "gwam"}` (ambos del DWD: EWAM alta resolución para
Europa, GWAM global como respaldo). Otros válidos: `ecmwf_wam`,
`meteofrance_wave`.

---

## 🔬 Cómo funciona (resumen técnico)

1. **Una llamada a la Forecast API** de Open-Meteo para los datos auxiliares
   comunes a todos los modelos: viento horario (`wind_speed_10m`,
   `wind_direction_10m`) y orto/ocaso diarios (`sunrise`, `sunset`).
2. **Una llamada a la Marine API por cada modelo** de oleaje (EWAM, GWAM),
   pidiendo `wave_height`, `wave_period`, `wave_direction`,
   `swell_wave_height`, `swell_wave_period` y `wind_wave_height`, con
   `cell_selection=sea` para forzar una celda de mar.
3. **Cruce de datos.** Cada franja horaria se empareja con su viento
   correspondiente y se marca como diurna o nocturna según el orto/ocaso de
   su día, formando objetos `SurfSlot` con toda la información.
4. **Reintentos con back-off.** Si una API no responde, hasta 3 intentos con
   espera creciente. Si Open-Meteo rechaza la petición (HTTP 400), el script
   muestra el motivo exacto.
5. **Filtrado temporal.** Se conservan solo las franjas de pasado mañana y el
   día siguiente (ventana de 2 días, en horario local).
6. **Evaluación.** Cada franja se marca como surfeable o no según las 5
   condiciones. Se busca una racha de `CONSECUTIVE_SLOTS` franjas surfeables
   consecutivas (la noche resetea el contador: una racha de día + otra del
   día siguiente son dos rachas distintas, y cada una se evalúa por separado).
7. **Notificación.** Si hay racha, `POST` a la API de Telegram con el resumen,
   el enlace a la previsión visual y vista previa activada.

**Tolerancia a fallos:** si la Forecast API auxiliar falla, el monitor sigue
funcionando (no penaliza las franjas sin dato de viento ni filtra por luz si
no hay datos de sol; prefiere avisar a callar). Si un modelo de oleaje falla,
el otro se evalúa igual.

---

## 💸 Coste

Cero. GitHub Actions es gratuito dentro de cuota (este workflow consume
≈ 1 min por ejecución, 4 veces al día). Open-Meteo es gratuito para uso no
comercial sin clave ni registro. No hay servidor que mantener.

---

## 🧯 Solución de problemas

| Síntoma | Causa probable | Solución |
|---|---|---|
| `Faltan las coordenadas` | No creaste `SPOT_LATITUDE`/`SPOT_LONGITUDE` | Créalos en Secrets con los nombres exactos. |
| `Open-Meteo rechazo la peticion: ...` | Un parámetro mal formado o un id de modelo inválido | El log muestra el motivo exacto que da la API. |
| Un modelo dice "Sin datos; se omite" | Ese modelo no cubre esas coordenadas | EWAM solo cubre Europa; GWAM es global. Si EWAM falla, GWAM cubre. |
| `[aux] No se pudieron obtener datos auxiliares` | La Forecast API falló | No es crítico: el monitor sigue, pero esa ejecución no filtra por viento ni por luz. |
| No llega el mensaje a Telegram | Token o chat_id mal | Revisa los Secrets. Escribe un mensaje al bot antes de sacar el `chat_id`. |
| "Alertas enviadas: 0" siempre | No hay ventanas surfeables, o los umbrales son muy estrictos | Normal en un spot de swell débil. Si quieres más sensibilidad, baja los umbrales (ver Configuración). Usa `LOG_LEVEL: DEBUG` para ver qué falla en cada franja. |
| Una franja descartada con "fuera de horas de luz" | Esa hora cae antes del orto o después del ocaso (más el margen) | Es el comportamiento deseado. Si quieres aprovechar más luz tenue, baja `DAYLIGHT_MARGIN_MIN` (p. ej. a `15` o `0`). |
| El schedule no arranca solo | GitHub tarda en activar el primer schedule, o pausa workflows en repos inactivos ~60 días | Usa **Run workflow** y haz algún commit de vez en cuando. |

---

## 📜 Licencia

Código bajo licencia MIT. Datos de oleaje, viento y orto/ocaso por
**Open-Meteo** (CC BY 4.0), generados a partir de los modelos del Deutscher
Wetterdienst (DWD).
