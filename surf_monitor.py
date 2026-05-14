#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
surf_monitor.py  (Open-Meteo, logica orientada a surf en Castelldefels)
=======================================================================

Monitor automatico de condiciones de surf para Castelldefels (Barcelona).

FUENTE DE DATOS
    API publica y gratuita de Open-Meteo, dos endpoints:
      - Marine API   : oleaje (altura, periodo, swell, wind wave).
      - Forecast API : viento (velocidad y direccion).
    Los modelos de oleaje son los del servicio aleman DWD: EWAM (Europa,
    alta resolucion 5 km) y GWAM (global). Son los mismos que Windguru
    etiqueta como "ICON Wave" / "EWAM". No requiere clave de API.

POR QUE LA ALTURA DE OLA NO BASTA PARA SURF
    Una ola de 1 m puede ser surfeable (si viene del SWELL, oleaje de fondo
    ordenado) o inservible (si es WIND WAVE, oleaje de viento local picado).
    Ademas el PERIODO importa: con periodo corto la ola tiene poca energia.
    Y el VIENTO local puede destrozar una sesion que sobre el papel era buena.

CALIBRACION PARA CASTELLDEFELS
    Castelldefels es un spot mediterraneo de SWELL DEBIL: el oleaje de fondo
    raramente supera los 0.7-0.8 m, y el periodo raramente pasa de 5 s. Filtrar
    por un umbral alto de swell dejaria el monitor practicamente mudo. Por eso
    la logica usa la altura TOTAL como umbral de tamano, y mete la "calidad"
    (swell vs viento) y el viento como filtros adicionales.

LOGICA: una franja horaria se considera SURFEABLE si cumple las 4 condiciones:
    1. wave_height (altura total)  >= WAVE_THRESHOLD     (defecto 0.8 m)
    2. wave_period (periodo)       >= PERIOD_THRESHOLD   (defecto 4.0 s)
    3. wind_speed (viento)         <= WIND_MAX_KMH       (defecto 20 km/h)
    4. el wind wave NO aplasta al swell: wind_wave_height <=
       swell_wave_height * WIND_WAVE_DOMINANCE  (defecto 1.5)
       -> descarta mar picado donde el oleaje de viento domina claramente.

    Si hay >= CONSECUTIVE_SLOTS franjas surfeables seguidas (defecto 3),
    se envia una alerta por Telegram con el detalle de la racha.

Variables de entorno:
    TELEGRAM_BOT_TOKEN     Token del bot de Telegram (obligatorio para alertas).
    TELEGRAM_CHAT_ID       Chat/grupo destino (obligatorio para alertas).
    SPOT_LATITUDE          Latitud del spot (obligatorio). Ej: "41.25".
    SPOT_LONGITUDE         Longitud del spot (obligatorio). Ej: "2.00".
    SPOT_NAME              Nombre legible del spot (opcional). Ej: "Castelldefels".
    WAVE_THRESHOLD         Altura total minima en metros (defecto 0.8).
    PERIOD_THRESHOLD       Periodo minimo en segundos (defecto 4.0).
    WIND_MAX_KMH           Viento maximo en km/h (defecto 20).
    WIND_WAVE_DOMINANCE    Factor de dominancia del wind wave (defecto 1.5).
    CONSECUTIVE_SLOTS      Franjas consecutivas requeridas (defecto 3).
    TIMEZONE               Zona horaria IANA (defecto "Europe/Madrid").
    LOG_LEVEL              DEBUG / INFO / WARNING / ERROR (defecto INFO).
"""

from __future__ import annotations

import logging
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import requests

# ---------------------------------------------------------------------------
# CONFIGURACION
# ---------------------------------------------------------------------------

SPOT_LATITUDE: str | None = os.getenv("SPOT_LATITUDE")
SPOT_LONGITUDE: str | None = os.getenv("SPOT_LONGITUDE")
SPOT_NAME: str = os.getenv("SPOT_NAME", "Castelldefels")

# URL para revisar la prevision visual de forma comoda al recibir la alerta.
# El monitor NO usa esta web para los datos (usa Open-Meteo), pero Windguru
# ofrece una vista grafica util para confirmar las condiciones de un vistazo
# antes de decidir si ir. Cambiable via variable de entorno.
SPOT_FORECAST_URL: str = os.getenv(
    "SPOT_FORECAST_URL", "https://www.windguru.cz/201"
)

# --- Umbrales que definen si una franja es "surfeable" ---
# (1) Altura total de ola minima (metros).
WAVE_THRESHOLD: float = float(os.getenv("WAVE_THRESHOLD", "0.8"))
# (2) Periodo minimo (segundos). En el Mediterraneo el periodo es bajo.
PERIOD_THRESHOLD: float = float(os.getenv("PERIOD_THRESHOLD", "4.0"))
# (3) Viento maximo (km/h). Por encima, el mar se pica y la sesion se estropea.
WIND_MAX_KMH: float = float(os.getenv("WIND_MAX_KMH", "20"))
# (4) Dominancia del wind wave: si wind_wave > swell * este factor, es mar
#     picado y se descarta. 1.5 = el oleaje de viento puede ser hasta un 50%
#     mayor que el swell antes de considerarse "demasiado picado".
WIND_WAVE_DOMINANCE: float = float(os.getenv("WIND_WAVE_DOMINANCE", "1.5"))

# Numero de franjas horarias consecutivas surfeables que disparan la alerta.
CONSECUTIVE_SLOTS: int = int(os.getenv("CONSECUTIVE_SLOTS", "3"))

# Zona horaria. Open-Meteo devuelve las horas ya en local si se especifica.
TIMEZONE: str = os.getenv("TIMEZONE", "Europe/Madrid")

# Telegram.
TELEGRAM_BOT_TOKEN: str | None = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID: str | None = os.getenv("TELEGRAM_CHAT_ID")
TELEGRAM_API_URL: str = "https://api.telegram.org/bot{token}/sendMessage"

# ---------------------------------------------------------------------------
# MODELOS DE OLEAJE
# ---------------------------------------------------------------------------
# Open-Meteo NO tiene un modelo marino llamado "icon". El ICON Wave del DWD
# se publica dividido en:
#   "ewam" -> DWD EWAM: Europa, alta resolucion 5 km. El mejor para Castelldefels.
#   "gwam" -> DWD GWAM: global, 25 km. Segundo modelo / respaldo.
# La clave del dict es el nombre "bonito" que sale en la alerta; el valor es el
# identificador que entiende Open-Meteo. Otros validos: "ecmwf_wam",
# "meteofrance_wave".
MODELS: dict[str, str] = {
    "EWAM": "ewam",
    "GWAM": "gwam",
}

# Endpoints de Open-Meteo.
MARINE_API_URL: str = "https://marine-api.open-meteo.com/v1/marine"
FORECAST_API_URL: str = "https://api.open-meteo.com/v1/forecast"

# Variables de oleaje que pedimos a la Marine API.
MARINE_HOURLY_VARS: str = (
    "wave_height,wave_period,wave_direction,"
    "swell_wave_height,swell_wave_period,"
    "wind_wave_height"
)
# Variables de la Forecast API: solo viento.
FORECAST_HOURLY_VARS: str = "wind_speed_10m,wind_direction_10m"

# Reintentos de red.
MAX_RETRIES: int = 3
RETRY_BACKOFF_SECONDS: int = 8
REQUEST_TIMEOUT_SECONDS: int = 20

# Logging.
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("surf_monitor")


# ---------------------------------------------------------------------------
# ESTRUCTURAS DE DATOS
# ---------------------------------------------------------------------------

@dataclass
class SurfSlot:
    """
    Una franja horaria con todos los datos relevantes para surf.
    Los campos opcionales pueden ser None si la API no los trajo; la logica
    de is_surfable() lo gestiona de forma conservadora.
    """
    dt: datetime                        # Momento (horario local)
    wave_height: float                  # Altura total de ola (m)
    wave_period: float                  # Periodo de la ola (s)
    wave_direction: float | None        # Direccion de donde viene la ola (grados)
    swell_height: float | None          # Altura del oleaje de fondo / swell (m)
    swell_period: float | None          # Periodo del swell (s)
    wind_wave_height: float | None      # Altura del oleaje de viento local (m)
    wind_speed: float | None = None     # Velocidad del viento a 10 m (km/h)
    wind_direction: float | None = None  # Direccion del viento (grados)

    def is_surfable(self) -> tuple[bool, str]:
        """
        Evalua si la franja es surfeable. Devuelve (es_surfable, motivo).
        El 'motivo' explica por que NO lo es (util para los logs en DEBUG).

        Las 4 condiciones (ver cabecera del archivo):
          1. altura total >= WAVE_THRESHOLD
          2. periodo >= PERIOD_THRESHOLD
          3. viento <= WIND_MAX_KMH
          4. wind wave no aplasta al swell

        Criterio conservador con datos faltantes:
          - Si falta altura o periodo: NO surfeable (no podemos evaluar).
          - Si falta el viento: no penalizamos por esa condicion (la Forecast
            API puede haber fallado; mejor avisar que callar). Se anota.
          - Si falta swell o wind wave: no aplicamos la condicion 4.
        """
        # (1) Altura total.
        if self.wave_height < WAVE_THRESHOLD:
            return False, f"altura {self.wave_height:.2f}m < {WAVE_THRESHOLD}m"

        # (2) Periodo.
        if self.wave_period < PERIOD_THRESHOLD:
            return False, f"periodo {self.wave_period:.1f}s < {PERIOD_THRESHOLD}s"

        # (3) Viento. Si no hay dato, no penalizamos (pero lo anotamos).
        if self.wind_speed is not None and self.wind_speed > WIND_MAX_KMH:
            return False, f"viento {self.wind_speed:.0f}km/h > {WIND_MAX_KMH}km/h"

        # (4) El wind wave no debe aplastar al swell.
        if (
            self.swell_height is not None
            and self.wind_wave_height is not None
            and self.swell_height > 0
            and self.wind_wave_height > self.swell_height * WIND_WAVE_DOMINANCE
        ):
            return False, (
                f"mar picado (wind {self.wind_wave_height:.2f}m vs "
                f"swell {self.swell_height:.2f}m)"
            )

        return True, "OK"

    def quality_label(self) -> str:
        """
        Etiqueta informativa de la calidad del mar:
          - "limpio"  si el swell predomina sobre el oleaje de viento.
          - "picado"  si el oleaje de viento predomina.
          - "mixto"   si estan parejos o falta el dato.
        """
        if self.swell_height is None or self.wind_wave_height is None:
            return "mixto"
        if self.swell_height >= self.wind_wave_height * 1.2:
            return "limpio"
        if self.wind_wave_height >= self.swell_height * 1.2:
            return "picado"
        return "mixto"

    def __repr__(self) -> str:
        ok, _ = self.is_surfable()
        return (
            f"<{self.dt:%Y-%m-%d %H:%M} "
            f"H={self.wave_height:.2f}m T={self.wave_period:.1f}s "
            f"{'OK' if ok else '--'}>"
        )


@dataclass
class ModelForecast:
    """Prevision completa para un modelo (EWAM, GWAM, ...)."""
    name: str
    slots: list[SurfSlot] = field(default_factory=list)


# ---------------------------------------------------------------------------
# DESCARGA DE DATOS DESDE OPEN-METEO
# ---------------------------------------------------------------------------

def _request_with_retries(url: str, params: dict, label: str) -> dict:
    """
    GET con reintentos y back-off exponencial. Devuelve el JSON parseado o
    lanza RuntimeError. 'label' es solo para los mensajes de log.
    """
    last_err: Exception | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            log.debug("[%s] GET %s params=%s (intento %d)", label, url, params, attempt)
            resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)

            # Open-Meteo devuelve 400 con {"error": true, "reason": ...}
            # cuando un parametro es incorrecto. Mostramos el motivo exacto.
            if resp.status_code == 400:
                try:
                    reason = resp.json().get("reason", "desconocido")
                except Exception:
                    reason = resp.text[:200]
                raise RuntimeError(f"Open-Meteo rechazo la peticion: {reason}")

            resp.raise_for_status()
            return resp.json()

        except (requests.RequestException, RuntimeError, ValueError) as e:
            last_err = e
            log.warning("[%s] Fallo en intento %d/%d: %s", label, attempt, MAX_RETRIES, e)
            if attempt < MAX_RETRIES:
                sleep_s = RETRY_BACKOFF_SECONDS * attempt
                log.info("[%s] Reintentando en %d s...", label, sleep_s)
                time.sleep(sleep_s)

    raise RuntimeError(
        f"[{label}] No se pudo consultar Open-Meteo tras {MAX_RETRIES} intentos: {last_err}"
    )


def _safe_get(arr: list | None, i: int) -> float | None:
    """Devuelve arr[i] como float, o None si no existe o es null."""
    if arr is None or i >= len(arr):
        return None
    v = arr[i]
    if v is None:
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def fetch_wind_forecast() -> dict[str, tuple[float | None, float | None]]:
    """
    Descarga el viento de la Forecast API de Open-Meteo. Devuelve un dict
    {timestamp_iso: (wind_speed_kmh, wind_direction_deg)}.

    Si esta llamada falla, NO es critico: devolvemos dict vacio. La logica de
    is_surfable() no penaliza las franjas sin dato de viento.
    """
    params = {
        "latitude": SPOT_LATITUDE,
        "longitude": SPOT_LONGITUDE,
        "hourly": FORECAST_HOURLY_VARS,
        "forecast_days": 4,
        "timezone": TIMEZONE,
        # wind_speed_unit por defecto es km/h, lo dejamos explicito.
        "wind_speed_unit": "kmh",
    }
    try:
        log.info("[viento] Consultando Forecast API de Open-Meteo...")
        payload = _request_with_retries(FORECAST_API_URL, params, "viento")
    except Exception as e:
        log.warning("[viento] No se pudo obtener el viento (no critico): %s", e)
        return {}

    hourly = payload.get("hourly", {})
    times = hourly.get("time", [])
    speeds = hourly.get("wind_speed_10m", [])
    dirs = hourly.get("wind_direction_10m", [])

    wind_map: dict[str, tuple[float | None, float | None]] = {}
    for i, t in enumerate(times):
        wind_map[t] = (_safe_get(speeds, i), _safe_get(dirs, i))

    log.info("[viento] Obtenidos datos de viento para %d franjas.", len(wind_map))
    return wind_map


def fetch_model_forecast(
    model_label: str,
    model_id: str,
    wind_map: dict[str, tuple[float | None, float | None]],
) -> ModelForecast:
    """
    Descarga la prevision de oleaje para un modelo concreto y la cruza con el
    viento ya descargado. Devuelve un ModelForecast con la lista de SurfSlot.
    """
    params = {
        "latitude": SPOT_LATITUDE,
        "longitude": SPOT_LONGITUDE,
        "hourly": MARINE_HOURLY_VARS,
        # 4 dias: hoy, manana, pasado manana y el dia siguiente.
        "forecast_days": 4,
        "timezone": TIMEZONE,
        "models": model_id,
        "length_unit": "metric",
        # Preferimos celda de MAR para evitar nulls cerca de la costa.
        "cell_selection": "sea",
    }

    log.info("[%s] Consultando Open-Meteo Marine (modelo '%s')...", model_label, model_id)
    payload = _request_with_retries(MARINE_API_URL, params, model_label)

    # Open-Meteo "encaja" la peticion a la celda de modelo mas cercana. Si la
    # celda devuelta esta lejos de la pedida, conviene saberlo.
    resp_lat = payload.get("latitude")
    resp_lon = payload.get("longitude")
    log.info(
        "[%s] Open-Meteo respondio para lat=%s lon=%s (pedido: %s, %s).",
        model_label, resp_lat, resp_lon, SPOT_LATITUDE, SPOT_LONGITUDE,
    )

    hourly = payload.get("hourly")
    if not isinstance(hourly, dict):
        log.warning("[%s] La respuesta no contiene bloque 'hourly'.", model_label)
        return ModelForecast(name=model_label, slots=[])

    times = hourly.get("time", [])
    h_wave = hourly.get("wave_height", [])
    h_period = hourly.get("wave_period", [])
    h_wavedir = hourly.get("wave_direction", [])
    h_swell_h = hourly.get("swell_wave_height", [])
    h_swell_p = hourly.get("swell_wave_period", [])
    h_wind_w = hourly.get("wind_wave_height", [])

    if not times or not h_wave:
        log.warning("[%s] Faltan 'time' o 'wave_height' en la respuesta.", model_label)
        return ModelForecast(name=model_label, slots=[])

    slots: list[SurfSlot] = []
    skipped = 0
    for i, t in enumerate(times):
        wh = _safe_get(h_wave, i)
        wp = _safe_get(h_period, i)
        # Sin altura o sin periodo no podemos evaluar la franja.
        if wh is None or wp is None:
            skipped += 1
            continue
        try:
            slot_dt = datetime.fromisoformat(t)
        except ValueError:
            skipped += 1
            continue

        wind_speed, wind_dir = wind_map.get(t, (None, None))

        slots.append(SurfSlot(
            dt=slot_dt,
            wave_height=wh,
            wave_period=wp,
            wave_direction=_safe_get(h_wavedir, i),
            swell_height=_safe_get(h_swell_h, i),
            swell_period=_safe_get(h_swell_p, i),
            wind_wave_height=_safe_get(h_wind_w, i),
            wind_speed=wind_speed,
            wind_direction=wind_dir,
        ))

    if skipped:
        log.debug("[%s] %d franjas descartadas por datos incompletos.", model_label, skipped)
    log.info("[%s] Obtenidas %d franjas con datos completos.", model_label, len(slots))
    return ModelForecast(name=model_label, slots=slots)


def fetch_all_forecasts() -> dict[str, ModelForecast]:
    """
    Descarga el viento una sola vez y luego la prevision de oleaje de cada
    modelo. Si un modelo falla, se registra pero NO se aborta.
    """
    # El viento es comun a todos los modelos: una sola llamada.
    wind_map = fetch_wind_forecast()

    forecasts: dict[str, ModelForecast] = {}
    for model_label, model_id in MODELS.items():
        try:
            forecasts[model_label] = fetch_model_forecast(model_label, model_id, wind_map)
        except Exception as e:
            log.error("[%s] No se pudo obtener la prevision: %s", model_label, e)

    if not forecasts:
        raise RuntimeError("No se obtuvo prevision de ningun modelo.")

    return forecasts


# ---------------------------------------------------------------------------
# LOGICA DE NEGOCIO: FILTRADO Y DETECCION
# ---------------------------------------------------------------------------

def get_target_window(reference: datetime | None = None) -> tuple[datetime, datetime]:
    """
    Devuelve el rango [inicio, fin) que cubre 'pasado manana' y el dia
    siguiente, como datetimes a medianoche en horario LOCAL.
    """
    ref = reference or datetime.now()
    day_after_tomorrow = (ref + timedelta(days=2)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    end = day_after_tomorrow + timedelta(days=2)  # exclusivo: cubre 2 dias
    return day_after_tomorrow, end


def filter_slots_for_window(slots: list[SurfSlot]) -> list[SurfSlot]:
    """
    Conserva solo las franjas dentro de la ventana de interes
    (pasado manana + el dia siguiente). Devuelve la lista ordenada por tiempo.
    """
    start, end = get_target_window()
    filtered = [s for s in slots if start <= s.dt < end]
    filtered.sort(key=lambda s: s.dt)
    return filtered


def find_surfable_streak(
    slots: list[SurfSlot],
    min_consecutive: int = CONSECUTIVE_SLOTS,
) -> tuple[bool, list[SurfSlot]]:
    """
    Devuelve (True, [racha]) si existe al menos una secuencia de
    'min_consecutive' franjas consecutivas surfeables.

    Como Open-Meteo entrega datos horarios continuos, esto equivale a
    'min_consecutive' horas seguidas de condiciones surfeables.
    """
    streak: list[SurfSlot] = []
    for s in slots:
        surfable, _ = s.is_surfable()
        if surfable:
            streak.append(s)
            if len(streak) >= min_consecutive:
                return True, streak
        else:
            streak = []
    return False, []


# ---------------------------------------------------------------------------
# UTILIDADES DE PRESENTACION
# ---------------------------------------------------------------------------

def _degrees_to_compass(deg: float | None) -> str:
    """Convierte grados a punto cardinal (N, NE, E, ...). '?' si es None."""
    if deg is None:
        return "?"
    dirs = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
            "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    idx = int((deg + 11.25) % 360 / 22.5)
    return dirs[idx]


def _summarize_streak(streak: list[SurfSlot]) -> str:
    """
    Construye un resumen legible de la racha para el mensaje de Telegram.
    """
    first, last = streak[0], streak[-1]

    heights = [s.wave_height for s in streak]
    periods = [s.wave_period for s in streak]

    # Calidad predominante en la racha.
    labels = [s.quality_label() for s in streak]
    if labels.count("limpio") > labels.count("picado"):
        quality = "mar limpio (predomina el swell de fondo)"
    elif labels.count("picado") > labels.count("limpio"):
        quality = "mar algo movido (presencia de oleaje de viento)"
    else:
        quality = "mar mixto (swell y viento parejos)"

    # Viento medio de la racha (si hay dato).
    winds = [s.wind_speed for s in streak if s.wind_speed is not None]
    if winds:
        wind_avg = sum(winds) / len(winds)
        mid_dir = streak[len(streak) // 2].wind_direction
        wind_txt = f"{wind_avg:.0f} km/h del {_degrees_to_compass(mid_dir)}"
    else:
        wind_txt = "sin dato (no penalizado)"

    # Direccion de la ola (de la franja central como referencia).
    mid_wavedir = streak[len(streak) // 2].wave_direction
    wavedir_txt = _degrees_to_compass(mid_wavedir)

    lines = [
        f"  Franja: {first.dt:%H:%M} - {last.dt:%H:%M} del {first.dt:%d/%m}",
        f"  Altura: {min(heights):.2f} - {max(heights):.2f} m",
        f"  Periodo: {min(periods):.1f} - {max(periods):.1f} s",
        f"  Direccion de la ola: viene del {wavedir_txt}",
        f"  Calidad: {quality}",
        f"  Viento: {wind_txt}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# NOTIFICACION A TELEGRAM
# ---------------------------------------------------------------------------

def send_telegram_alert(model: str, streak: list[SurfSlot]) -> bool:
    """
    Envia el mensaje de alerta a Telegram. Devuelve True si se envio OK.
    Si no hay credenciales, solo muestra el mensaje por consola.
    """
    summary = _summarize_streak(streak)
    text = (
        "🏄 *Posible sesion de surf*\n\n"
        f"Spot: {SPOT_NAME}\n"
        f"Modelo: {model}\n\n"
        f"Detectadas {len(streak)} horas consecutivas surfeables:\n"
        f"olas de al menos {WAVE_THRESHOLD:.1f} m, periodo de al menos "
        f"{PERIOD_THRESHOLD:.1f} s y viento por debajo de "
        f"{WIND_MAX_KMH:.0f} km/h.\n\n"
        f"{summary}\n\n"
        "_El Mediterraneo tiene periodo corto; aun asi estas son de las "
        "mejores ventanas. Confirma el viento antes de ir: offshore (de "
        "tierra) lo mejora mucho._\n\n"
        f"🔗 Ver prevision completa: {SPOT_FORECAST_URL}\n\n"
        f"Fuente: Open-Meteo (modelo {model})"
    )

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning(
            "TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID no configurados. "
            "Mensaje que se enviaria:\n%s",
            text,
        )
        return False

    url = TELEGRAM_API_URL.format(token=TELEGRAM_BOT_TOKEN)
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        # Dejamos la preview ACTIVADA: asi el mensaje muestra una tarjeta
        # clicable de la web de prevision, comoda para abrir de un toque.
        "disable_web_page_preview": False,
    }

    try:
        r = requests.post(url, data=payload, timeout=15)
        r.raise_for_status()
        data = r.json()
        if not data.get("ok"):
            log.error("Telegram respondio no-OK: %s", data)
            return False
        log.info("Alerta Telegram enviada correctamente para modelo %s.", model)
        return True
    except requests.RequestException as e:
        log.error("Error enviando Telegram: %s", e)
        return False


# ---------------------------------------------------------------------------
# ORQUESTADOR
# ---------------------------------------------------------------------------

def evaluate_and_alert(forecasts: dict[str, ModelForecast]) -> int:
    """
    Evalua cada modelo y envia alerta si procede. Devuelve el numero de
    alertas enviadas.
    """
    alerts = 0
    start, end = get_target_window()
    log.info(
        "Ventana de evaluacion: %s -> %s (pasado manana + dia siguiente)",
        start.strftime("%Y-%m-%d"),
        (end - timedelta(seconds=1)).strftime("%Y-%m-%d"),
    )
    log.info(
        "Criterio surfeable: altura >= %.1fm Y periodo >= %.1fs Y "
        "viento <= %.0fkm/h Y wind wave no domina; %d franjas seguidas.",
        WAVE_THRESHOLD, PERIOD_THRESHOLD, WIND_MAX_KMH, CONSECUTIVE_SLOTS,
    )

    for model_label in MODELS:
        forecast = forecasts.get(model_label)
        if forecast is None or not forecast.slots:
            log.warning("[%s] Sin datos; se omite este modelo.", model_label)
            continue

        window_slots = filter_slots_for_window(forecast.slots)
        surfable_count = sum(1 for s in window_slots if s.is_surfable()[0])
        log.info(
            "[%s] %d franjas en la ventana, %d cumplen el criterio surfeable.",
            model_label, len(window_slots), surfable_count,
        )
        if log.isEnabledFor(logging.DEBUG):
            for s in window_slots:
                ok, reason = s.is_surfable()
                log.debug(
                    "  [%s] %s H=%.2fm T=%.1fs swell=%.2fm wind_wave=%.2fm "
                    "viento=%s -> %s",
                    "OK" if ok else "--", s.dt.isoformat(),
                    s.wave_height, s.wave_period,
                    s.swell_height if s.swell_height is not None else -1,
                    s.wind_wave_height if s.wind_wave_height is not None else -1,
                    f"{s.wind_speed:.0f}km/h" if s.wind_speed is not None else "?",
                    reason,
                )

        triggered, streak = find_surfable_streak(window_slots)
        if triggered:
            log.info(
                "[%s] ✅ Racha surfeable: %d horas desde %s.",
                model_label, len(streak), streak[0].dt.isoformat(),
            )
            if send_telegram_alert(model_label, streak):
                alerts += 1
        else:
            log.info("[%s] ❌ No hay racha surfeable suficiente.", model_label)

    return alerts


def validate_config() -> bool:
    """
    Comprueba la configuracion minima. Devuelve True si todo OK.
    """
    ok = True

    if not SPOT_LATITUDE or not SPOT_LONGITUDE:
        log.error(
            "Faltan las coordenadas. Define SPOT_LATITUDE y SPOT_LONGITUDE "
            "(ej: 41.25 y 2.00)."
        )
        ok = False
    else:
        try:
            lat = float(SPOT_LATITUDE)
            lon = float(SPOT_LONGITUDE)
            if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
                log.error("Coordenadas fuera de rango: lat=%s lon=%s", lat, lon)
                ok = False
        except ValueError:
            log.error(
                "SPOT_LATITUDE/SPOT_LONGITUDE no son numeros: %s, %s",
                SPOT_LATITUDE, SPOT_LONGITUDE,
            )
            ok = False

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning(
            "TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID no definidos: el script "
            "funcionara pero NO enviara alertas reales a Telegram."
        )

    return ok


def main() -> int:
    log.info("=== Surf Monitor (Open-Meteo) — spot '%s' ===", SPOT_NAME)
    log.info("Modelos a evaluar: %s", list(MODELS.keys()))

    if not validate_config():
        log.error("Configuracion invalida. Abortando.")
        return 2

    try:
        forecasts = fetch_all_forecasts()
    except Exception as e:
        log.error("No se pudo obtener prevision: %s", e)
        return 2

    log.info("Modelos obtenidos: %s", list(forecasts.keys()))
    alerts = evaluate_and_alert(forecasts)
    log.info("=== Ejecucion finalizada. Alertas enviadas: %d ===", alerts)
    return 0


if __name__ == "__main__":
    sys.exit(main())
