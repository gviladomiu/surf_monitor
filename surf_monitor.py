#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
surf_monitor.py  (Open-Meteo, multi-spot, orientado a surf en la costa de Barcelona)
====================================================================================

Monitor automatico de condiciones de surf para VARIOS spots de la costa de
Barcelona (Castelldefels, Masnou, Sitges...). Cada 6 horas revisa la prevision
de cada spot, evalua si hay una ventana surfeable a partir de las proximas
horas (el tiempo que necesitas para llegar al spot en coche), y avisa por
Telegram con un mensaje por cada spot que tenga olas.

FUENTE DE DATOS
    API publica y gratuita de Open-Meteo, dos endpoints:
      - Marine API   : oleaje (altura, periodo, swell, wind wave) + temperatura
                       del agua (sea_surface_temperature).
      - Forecast API : viento (velocidad y direccion) + orto/ocaso.
    Los modelos de oleaje son los del servicio aleman DWD: EWAM (Europa, alta
    resolucion 5 km) y GWAM (global). Son los mismos que Windguru etiqueta como
    "ICON Wave" / "EWAM". No requiere clave de API.

POR QUE LA ALTURA DE OLA NO BASTA PARA SURF
    Una ola de 1 m puede ser surfeable (si viene del SWELL, oleaje de fondo
    ordenado) o inservible (si es WIND WAVE, oleaje de viento local picado).
    Ademas el PERIODO importa (poca energia si es corto), el VIENTO puede
    destrozar la sesion, y de noche no se puede surfear.

LOGICA: una franja horaria se considera SURFEABLE si cumple las 5 condiciones:
    1. wave_height (altura total)  >= WAVE_THRESHOLD     (defecto 0.8 m)
    2. wave_period (periodo)       >= PERIOD_THRESHOLD   (defecto 4.0 s)
    3. wind_speed (viento)         <= WIND_MAX_KMH       (defecto 20 km/h)
    4. el wind wave NO aplasta al swell (factor WIND_WAVE_DOMINANCE)
    5. la franja esta en horas de luz (orto/ocaso + margen)

    Ademas, solo se consideran franjas a partir de AHORA + LEAD_TIME_HOURS
    (defecto 3 h), el tiempo necesario para desplazarse al spot.

    Si hay >= CONSECUTIVE_SLOTS franjas surfeables seguidas (defecto 3), el
    spot tiene una "ventana". Se manda UN mensaje por spot con ventana,
    combinando los dos modelos (EWAM y GWAM) y recomendando neopreno segun la
    temperatura del agua.

Variables de entorno:
    TELEGRAM_BOT_TOKEN     Token del bot de Telegram (obligatorio para alertas).
    TELEGRAM_CHAT_ID       Chat/grupo destino (obligatorio para alertas).
    WAVE_THRESHOLD         Altura total minima en metros (defecto 0.8).
    PERIOD_THRESHOLD       Periodo minimo en segundos (defecto 4.0).
    WIND_MAX_KMH           Viento maximo en km/h (defecto 20).
    WIND_WAVE_DOMINANCE    Factor de dominancia del wind wave (defecto 1.5).
    DAYLIGHT_MARGIN_MIN    Minutos de margen al amanecer/anochecer (defecto 30).
    LEAD_TIME_HOURS        Horas de antelacion minima para ir al spot (defecto 3).
    CONSECUTIVE_SLOTS      Franjas consecutivas requeridas (defecto 3).
    TIMEZONE               Zona horaria IANA (defecto "Europe/Madrid").
    LOG_LEVEL              DEBUG / INFO / WARNING / ERROR (defecto INFO).

NOTA: Los spots se definen en la lista SPOTS de este archivo (no por variables
de entorno, porque son varios y cada uno tiene nombre, coordenadas y URL).
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
# DEFINICION DE SPOTS
# ---------------------------------------------------------------------------
# Cada spot tiene: nombre, latitud, longitud y URL de prevision visual
# (Windguru, solo para el enlace de la alerta; los datos vienen de Open-Meteo).
#
# Para anadir o quitar spots, edita esta lista. Las coordenadas conviene que
# esten ligeramente MAR ADENTRO para que el modelo de oleaje tenga cobertura.

@dataclass
class Spot:
    name: str
    latitude: float
    longitude: float
    forecast_url: str


SPOTS: list[Spot] = [
    Spot(
        name="Castelldefels",
        latitude=41.25,
        longitude=2.00,
        forecast_url="https://www.windguru.cz/201",
    ),
    Spot(
        name="Masnou",
        latitude=41.474775,
        longitude=2.305556,
        forecast_url="https://www.windguru.cz/501030",
    ),
    Spot(
        name="Sitges",
        latitude=41.234065,
        longitude=1.820438,
        forecast_url="https://www.windguru.cz/48885",
    ),
]

# ---------------------------------------------------------------------------
# CONFIGURACION DE UMBRALES Y COMPORTAMIENTO
# ---------------------------------------------------------------------------

# --- Umbrales que definen si una franja es "surfeable" ---
# (1) Altura total de ola minima (metros).
WAVE_THRESHOLD: float = float(os.getenv("WAVE_THRESHOLD", "0.8"))
# (2) Periodo minimo (segundos). En el Mediterraneo el periodo es bajo.
PERIOD_THRESHOLD: float = float(os.getenv("PERIOD_THRESHOLD", "4.0"))
# (3) Viento maximo (km/h). Por encima, el mar se pica y la sesion se estropea.
WIND_MAX_KMH: float = float(os.getenv("WIND_MAX_KMH", "20"))
# (4) Dominancia del wind wave: si wind_wave > swell * este factor, es mar
#     picado y se descarta.
WIND_WAVE_DOMINANCE: float = float(os.getenv("WIND_WAVE_DOMINANCE", "1.5"))
# (5) Solo horas con luz solar. Margen en minutos al amanecer/anochecer.
DAYLIGHT_MARGIN_MIN: int = int(os.getenv("DAYLIGHT_MARGIN_MIN", "30"))

# Antelacion minima: solo miramos franjas a partir de AHORA + estas horas,
# que es el tiempo que necesitas para coger el coche e ir al spot.
LEAD_TIME_HOURS: float = float(os.getenv("LEAD_TIME_HOURS", "3"))

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
# Open-Meteo NO tiene un modelo marino llamado "icon". El ICON Wave del DWD se
# publica dividido en:
#   "ewam" -> DWD EWAM: Europa, alta resolucion 5 km. El mejor para esta costa.
#   "gwam" -> DWD GWAM: global, 25 km. Segundo modelo / respaldo.
# Otros validos: "ecmwf_wam", "meteofrance_wave".
MODELS: dict[str, str] = {
    "EWAM": "ewam",
    "GWAM": "gwam",
}

# Endpoints de Open-Meteo.
MARINE_API_URL: str = "https://marine-api.open-meteo.com/v1/marine"
FORECAST_API_URL: str = "https://api.open-meteo.com/v1/forecast"

# Variables de oleaje que pedimos a la Marine API (incluye temperatura del agua).
MARINE_HOURLY_VARS: str = (
    "wave_height,wave_period,wave_direction,"
    "swell_wave_height,swell_wave_period,"
    "wind_wave_height,sea_surface_temperature"
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
class AuxiliaryData:
    """
    Datos auxiliares comunes a todos los modelos de UN spot (no dependen del
    modelo de oleaje), de la Forecast API:
      - wind_map: viento horario por timestamp ISO.
      - daylight_by_date: por fecha, (inicio_luz, fin_luz) con margen aplicado.
    Si la llamada falla, las estructuras quedan vacias (criterio conservador).
    """
    wind_map: dict[str, tuple[float | None, float | None]] = field(default_factory=dict)
    daylight_by_date: dict[str, tuple[datetime, datetime]] = field(default_factory=dict)


@dataclass
class SurfSlot:
    """
    Una franja horaria con todos los datos relevantes para surf.
    Los campos opcionales pueden ser None si la API no los trajo; la logica de
    is_surfable() lo gestiona de forma conservadora.
    """
    dt: datetime                        # Momento (horario local)
    wave_height: float                  # Altura total de ola (m)
    wave_period: float                  # Periodo de la ola (s)
    wave_direction: float | None        # Direccion de donde viene la ola (grados)
    swell_height: float | None          # Altura del oleaje de fondo / swell (m)
    swell_period: float | None          # Periodo del swell (s)
    wind_wave_height: float | None      # Altura del oleaje de viento local (m)
    water_temp: float | None = None     # Temperatura del agua (C)
    wind_speed: float | None = None     # Velocidad del viento a 10 m (km/h)
    wind_direction: float | None = None  # Direccion del viento (grados)
    is_daylight: bool = True             # ¿Hay luz solar en esta franja?

    def is_surfable(self) -> tuple[bool, str]:
        """
        Evalua si la franja es surfeable. Devuelve (es_surfable, motivo).
        Las 5 condiciones (ver cabecera). Criterio conservador con datos
        faltantes: si falta altura/periodo -> no surfeable; si falta viento o
        sol -> no penaliza por esa condicion.
        """
        if self.wave_height < WAVE_THRESHOLD:
            return False, f"altura {self.wave_height:.2f}m < {WAVE_THRESHOLD}m"
        if self.wave_period < PERIOD_THRESHOLD:
            return False, f"periodo {self.wave_period:.1f}s < {PERIOD_THRESHOLD}s"
        if self.wind_speed is not None and self.wind_speed > WIND_MAX_KMH:
            return False, f"viento {self.wind_speed:.0f}km/h > {WIND_MAX_KMH}km/h"
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
        if not self.is_daylight:
            return False, "fuera de horas de luz (orto-ocaso)"
        return True, "OK"

    def quality_label(self) -> str:
        """Calidad del mar: limpio / picado / mixto (informativo)."""
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
    """Prevision de un modelo (EWAM, GWAM) para un spot."""
    name: str
    slots: list[SurfSlot] = field(default_factory=list)


@dataclass
class SpotResult:
    """
    Resultado de evaluar un spot: las rachas surfeables encontradas por modelo
    y la temperatura del agua representativa.
    """
    spot: Spot
    streaks_by_model: dict[str, list[list[SurfSlot]]] = field(default_factory=dict)
    water_temp: float | None = None

    def has_window(self) -> bool:
        """True si algun modelo encontro al menos una racha."""
        return any(streaks for streaks in self.streaks_by_model.values())


# ---------------------------------------------------------------------------
# NEOPRENO SEGUN TEMPERATURA DEL AGUA
# ---------------------------------------------------------------------------
# Recomendacion de grosor de neopreno para una sesion de 2-3 h (exposicion
# prolongada, por lo que se tiende a abrigar un punto mas que para un bano
# corto). Los rangos son los habituales en guias de surf para aguas templadas.

def wetsuit_recommendation(water_temp: float | None) -> str:
    """
    Devuelve una recomendacion de neopreno en texto segun la temperatura del
    agua, pensada para una sesion larga (2-3 h). Si no hay dato, lo indica.
    """
    if water_temp is None:
        return "sin dato de temperatura del agua"

    t = water_temp
    if t >= 24:
        return f"agua ~{t:.0f}C: lycra o sin neopreno (a lo sumo top de 1-2 mm)"
    if t >= 22:
        return f"agua ~{t:.0f}C: shorty 2 mm o neopreno corto"
    if t >= 19:
        return f"agua ~{t:.0f}C: neopreno 3/2 mm"
    if t >= 16:
        return f"agua ~{t:.0f}C: neopreno 4/3 mm (valora escarpines)"
    if t >= 13:
        return f"agua ~{t:.0f}C: neopreno 5/4 mm + escarpines; guantes y capucha si aguantas 2-3 h"
    return f"agua ~{t:.0f}C: 5/4 mm o mas, con capucha, guantes y escarpines (sesion larga exige abrigo extra)"


# ---------------------------------------------------------------------------
# DESCARGA DE DATOS DESDE OPEN-METEO
# ---------------------------------------------------------------------------

def _request_with_retries(url: str, params: dict, label: str) -> dict:
    """GET con reintentos y back-off exponencial. Devuelve JSON o lanza."""
    last_err: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            log.debug("[%s] GET %s params=%s (intento %d)", label, url, params, attempt)
            resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
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


def fetch_auxiliary_data(spot: Spot) -> AuxiliaryData:
    """
    Descarga viento + orto/ocaso de la Forecast API para un spot concreto.
    Si falla, devuelve AuxiliaryData vacio (criterio conservador).
    """
    params = {
        "latitude": spot.latitude,
        "longitude": spot.longitude,
        "hourly": FORECAST_HOURLY_VARS,
        "daily": "sunrise,sunset",
        "forecast_days": 4,
        "timezone": TIMEZONE,
        "wind_speed_unit": "kmh",
    }
    label = f"{spot.name}/aux"
    try:
        log.info("[%s] Consultando Forecast API (viento + sol)...", label)
        payload = _request_with_retries(FORECAST_API_URL, params, label)
    except Exception as e:
        log.warning("[%s] No se pudieron obtener datos auxiliares (no critico): %s", label, e)
        return AuxiliaryData()

    aux = AuxiliaryData()
    hourly = payload.get("hourly", {})
    times = hourly.get("time", [])
    speeds = hourly.get("wind_speed_10m", [])
    dirs = hourly.get("wind_direction_10m", [])
    for i, t in enumerate(times):
        aux.wind_map[t] = (_safe_get(speeds, i), _safe_get(dirs, i))

    daily = payload.get("daily", {})
    dates = daily.get("time", [])
    sunrises = daily.get("sunrise", [])
    sunsets = daily.get("sunset", [])
    margin = timedelta(minutes=DAYLIGHT_MARGIN_MIN)
    for i, d in enumerate(dates):
        try:
            sr = datetime.fromisoformat(sunrises[i]) + margin
            ss = datetime.fromisoformat(sunsets[i]) - margin
            aux.daylight_by_date[d] = (sr, ss)
        except (ValueError, TypeError, IndexError):
            pass

    log.info(
        "[%s] Viento: %d franjas. Luz solar: %d dias.",
        label, len(aux.wind_map), len(aux.daylight_by_date),
    )
    return aux


def fetch_model_forecast(spot: Spot, model_label: str, model_id: str, aux: AuxiliaryData) -> ModelForecast:
    """
    Descarga la prevision de oleaje de un modelo para un spot y la cruza con
    viento y luz. Devuelve un ModelForecast con la lista de SurfSlot.
    """
    params = {
        "latitude": spot.latitude,
        "longitude": spot.longitude,
        "hourly": MARINE_HOURLY_VARS,
        "forecast_days": 4,
        "timezone": TIMEZONE,
        "models": model_id,
        "length_unit": "metric",
        "cell_selection": "sea",
    }
    label = f"{spot.name}/{model_label}"
    log.info("[%s] Consultando Open-Meteo Marine (modelo '%s')...", label, model_id)
    payload = _request_with_retries(MARINE_API_URL, params, label)

    log.info(
        "[%s] Open-Meteo respondio para lat=%s lon=%s (pedido: %s, %s).",
        label, payload.get("latitude"), payload.get("longitude"),
        spot.latitude, spot.longitude,
    )

    hourly = payload.get("hourly")
    if not isinstance(hourly, dict):
        log.warning("[%s] La respuesta no contiene bloque 'hourly'.", label)
        return ModelForecast(name=model_label, slots=[])

    times = hourly.get("time", [])
    h_wave = hourly.get("wave_height", [])
    h_period = hourly.get("wave_period", [])
    h_wavedir = hourly.get("wave_direction", [])
    h_swell_h = hourly.get("swell_wave_height", [])
    h_swell_p = hourly.get("swell_wave_period", [])
    h_wind_w = hourly.get("wind_wave_height", [])
    h_water = hourly.get("sea_surface_temperature", [])

    if not times or not h_wave:
        log.warning("[%s] Faltan 'time' o 'wave_height'.", label)
        return ModelForecast(name=model_label, slots=[])

    slots: list[SurfSlot] = []
    skipped = 0
    for i, t in enumerate(times):
        wh = _safe_get(h_wave, i)
        wp = _safe_get(h_period, i)
        if wh is None or wp is None:
            skipped += 1
            continue
        try:
            slot_dt = datetime.fromisoformat(t)
        except ValueError:
            skipped += 1
            continue

        wind_speed, wind_dir = aux.wind_map.get(t, (None, None))

        date_key = slot_dt.strftime("%Y-%m-%d")
        daylight_range = aux.daylight_by_date.get(date_key)
        if daylight_range is not None:
            sunrise, sunset = daylight_range
            is_daylight = sunrise <= slot_dt <= sunset
        else:
            is_daylight = True

        slots.append(SurfSlot(
            dt=slot_dt,
            wave_height=wh,
            wave_period=wp,
            wave_direction=_safe_get(h_wavedir, i),
            swell_height=_safe_get(h_swell_h, i),
            swell_period=_safe_get(h_swell_p, i),
            wind_wave_height=_safe_get(h_wind_w, i),
            water_temp=_safe_get(h_water, i),
            wind_speed=wind_speed,
            wind_direction=wind_dir,
            is_daylight=is_daylight,
        ))

    if skipped:
        log.debug("[%s] %d franjas descartadas por datos incompletos.", label, skipped)
    log.info("[%s] Obtenidas %d franjas con datos completos.", label, len(slots))
    return ModelForecast(name=model_label, slots=slots)


# ---------------------------------------------------------------------------
# LOGICA DE NEGOCIO: VENTANA TEMPORAL, FILTRADO Y DETECCION
# ---------------------------------------------------------------------------

def get_search_start(reference: datetime | None = None) -> datetime:
    """
    Devuelve el momento a partir del cual buscamos ventanas: AHORA mas el
    tiempo de antelacion (LEAD_TIME_HOURS), redondeado hacia arriba a la hora
    en punto (los datos de Open-Meteo son horarios).
    """
    ref = reference or datetime.now()
    start = ref + timedelta(hours=LEAD_TIME_HOURS)
    # Redondear hacia arriba a la siguiente hora en punto.
    if start.minute > 0 or start.second > 0 or start.microsecond > 0:
        start = start.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    else:
        start = start.replace(minute=0, second=0, microsecond=0)
    return start


def filter_slots_from_now(slots: list[SurfSlot], reference: datetime | None = None) -> list[SurfSlot]:
    """
    Conserva solo las franjas a partir de AHORA + LEAD_TIME_HOURS, ordenadas.
    Miramos hacia delante hasta el final de los datos disponibles (~4 dias).
    """
    start = get_search_start(reference)
    filtered = [s for s in slots if s.dt >= start]
    filtered.sort(key=lambda s: s.dt)
    return filtered


def find_all_surfable_streaks(
    slots: list[SurfSlot],
    min_consecutive: int = CONSECUTIVE_SLOTS,
) -> list[list[SurfSlot]]:
    """
    Devuelve TODAS las rachas de 'min_consecutive'+ franjas consecutivas
    surfeables, en orden cronologico. Una franja no-surfeable corta la racha.
    """
    streaks: list[list[SurfSlot]] = []
    current: list[SurfSlot] = []
    for s in slots:
        surfable, _ = s.is_surfable()
        if surfable:
            current.append(s)
        else:
            if len(current) >= min_consecutive:
                streaks.append(current)
            current = []
    if len(current) >= min_consecutive:
        streaks.append(current)
    return streaks


def representative_water_temp(forecasts: dict[str, ModelForecast], reference: datetime | None = None) -> float | None:
    """
    Temperatura del agua representativa para el spot: la del primer slot futuro
    con dato (la mas cercana en el tiempo a partir de la ventana de busqueda).
    """
    start = get_search_start(reference)
    for forecast in forecasts.values():
        for s in sorted(forecast.slots, key=lambda x: x.dt):
            if s.dt >= start and s.water_temp is not None:
                return s.water_temp
    # Si no hay nada futuro, probar cualquier dato disponible.
    for forecast in forecasts.values():
        for s in forecast.slots:
            if s.water_temp is not None:
                return s.water_temp
    return None


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
    """Resumen legible de una racha para el mensaje de Telegram."""
    first, last = streak[0], streak[-1]
    heights = [s.wave_height for s in streak]
    periods = [s.wave_period for s in streak]

    labels = [s.quality_label() for s in streak]
    if labels.count("limpio") > labels.count("picado"):
        quality = "mar limpio (predomina el swell de fondo)"
    elif labels.count("picado") > labels.count("limpio"):
        quality = "mar algo movido (presencia de oleaje de viento)"
    else:
        quality = "mar mixto (swell y viento parejos)"

    winds = [s.wind_speed for s in streak if s.wind_speed is not None]
    if winds:
        wind_avg = sum(winds) / len(winds)
        mid_dir = streak[len(streak) // 2].wind_direction
        wind_txt = f"{wind_avg:.0f} km/h del {_degrees_to_compass(mid_dir)}"
    else:
        wind_txt = "sin dato"

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


def build_spot_message(result: SpotResult) -> str:
    """
    Construye el mensaje de Telegram para UN spot, combinando los dos modelos
    (EWAM y GWAM) y anadiendo temperatura del agua y recomendacion de neopreno.
    """
    spot = result.spot

    # Cabecera con temperatura del agua y neopreno.
    temp = result.water_temp
    temp_txt = f"{temp:.0f}C" if temp is not None else "sin dato"
    wetsuit = wetsuit_recommendation(temp)

    partes = [
        "🏄 *Ventana de surf detectada*",
        "",
        f"Spot: *{spot.name}*",
        f"Agua: {temp_txt}",
        f"Neopreno (sesion 2-3 h): {wetsuit}",
        "",
        f"Criterio: olas >= {WAVE_THRESHOLD:.1f} m, periodo >= "
        f"{PERIOD_THRESHOLD:.1f} s, viento < {WIND_MAX_KMH:.0f} km/h, con luz, "
        f"a partir de +{LEAD_TIME_HOURS:.0f} h.",
    ]

    # Bloque por cada modelo que tenga rachas.
    for model_label in MODELS:
        streaks = result.streaks_by_model.get(model_label, [])
        if not streaks:
            continue
        partes.append("")
        n = len(streaks)
        if n == 1:
            partes.append(f"*Modelo {model_label}* — 1 ventana:")
        else:
            partes.append(f"*Modelo {model_label}* — {n} ventanas:")
        for i, streak in enumerate(streaks, start=1):
            etiqueta = f"  Ventana {i} ({len(streak)} h)" if n > 1 else f"  ({len(streak)} h)"
            partes.append(etiqueta)
            partes.append(_summarize_streak(streak))

    partes.append("")
    partes.append(f"🔗 Ver prevision completa: {spot.forecast_url}")
    partes.append("")
    partes.append("Fuente: Open-Meteo (modelos EWAM y GWAM, DWD)")

    return "\n".join(partes)


# ---------------------------------------------------------------------------
# NOTIFICACION A TELEGRAM
# ---------------------------------------------------------------------------

def send_telegram_message(text: str) -> bool:
    """Envia un mensaje a Telegram. Devuelve True si se envio OK."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning(
            "TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID no configurados. "
            "Mensaje que se enviaria:\n%s", text,
        )
        return False

    url = TELEGRAM_API_URL.format(token=TELEGRAM_BOT_TOKEN)
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False,
    }
    try:
        r = requests.post(url, data=payload, timeout=15)
        r.raise_for_status()
        data = r.json()
        if not data.get("ok"):
            log.error("Telegram respondio no-OK: %s", data)
            return False
        log.info("Mensaje de Telegram enviado correctamente.")
        return True
    except requests.RequestException as e:
        log.error("Error enviando Telegram: %s", e)
        return False


# ---------------------------------------------------------------------------
# ORQUESTADOR
# ---------------------------------------------------------------------------

def evaluate_spot(spot: Spot) -> SpotResult:
    """
    Evalua un spot completo: descarga aux + cada modelo, filtra desde +lead
    time, busca rachas por modelo, y calcula la temperatura del agua.
    """
    result = SpotResult(spot=spot)

    aux = fetch_auxiliary_data(spot)

    forecasts: dict[str, ModelForecast] = {}
    for model_label, model_id in MODELS.items():
        try:
            forecasts[model_label] = fetch_model_forecast(spot, model_label, model_id, aux)
        except Exception as e:
            log.error("[%s/%s] No se pudo obtener la prevision: %s", spot.name, model_label, e)

    if not forecasts:
        log.warning("[%s] Sin datos de ningun modelo.", spot.name)
        return result

    result.water_temp = representative_water_temp(forecasts)

    for model_label, forecast in forecasts.items():
        if not forecast.slots:
            continue
        window_slots = filter_slots_from_now(forecast.slots)
        surfable_count = sum(1 for s in window_slots if s.is_surfable()[0])
        log.info(
            "[%s/%s] %d franjas desde +%.0fh, %d surfeables.",
            spot.name, model_label, len(window_slots), LEAD_TIME_HOURS, surfable_count,
        )
        streaks = find_all_surfable_streaks(window_slots)
        if streaks:
            result.streaks_by_model[model_label] = streaks
            log.info(
                "[%s/%s] ✅ %d racha(s) detectada(s).",
                spot.name, model_label, len(streaks),
            )
        else:
            log.info("[%s/%s] ❌ Sin racha surfeable.", spot.name, model_label)

    return result


def run() -> int:
    log.info("=== Surf Monitor (Open-Meteo) — %d spots ===", len(SPOTS))
    log.info("Spots: %s", ", ".join(s.name for s in SPOTS))
    log.info(
        "Criterio: altura >= %.1fm, periodo >= %.1fs, viento <= %.0fkm/h, "
        "luz (margen %dmin), a partir de +%.0fh, %d franjas seguidas.",
        WAVE_THRESHOLD, PERIOD_THRESHOLD, WIND_MAX_KMH,
        DAYLIGHT_MARGIN_MIN, LEAD_TIME_HOURS, CONSECUTIVE_SLOTS,
    )

    messages_sent = 0
    spots_with_window = 0

    for spot in SPOTS:
        log.info("--- Evaluando spot: %s ---", spot.name)
        try:
            result = evaluate_spot(spot)
        except Exception as e:
            log.error("[%s] Error evaluando el spot: %s", spot.name, e)
            continue

        if result.has_window():
            spots_with_window += 1
            message = build_spot_message(result)
            if send_telegram_message(message):
                messages_sent += 1
        else:
            log.info("[%s] Sin ventana surfeable; no se notifica.", spot.name)

    log.info(
        "=== Fin. %d spot(s) con ventana, %d mensaje(s) enviado(s). ===",
        spots_with_window, messages_sent,
    )
    return 0


def validate_config() -> bool:
    """Comprueba la configuracion minima. Devuelve True si todo OK."""
    ok = True
    if not SPOTS:
        log.error("No hay spots definidos en la lista SPOTS.")
        ok = False
    for s in SPOTS:
        if not (-90 <= s.latitude <= 90) or not (-180 <= s.longitude <= 180):
            log.error("Spot %s con coordenadas fuera de rango.", s.name)
            ok = False
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning(
            "TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID no definidos: el script "
            "funcionara pero NO enviara alertas reales a Telegram."
        )
    return ok


def main() -> int:
    if not validate_config():
        log.error("Configuracion invalida. Abortando.")
        return 2
    return run()


if __name__ == "__main__":
    sys.exit(main())
