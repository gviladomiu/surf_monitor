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
                       del agua (sea_surface_temperature, sin forzar modelo).
      - Forecast API : viento (velocidad y direccion) + orto/ocaso.
    Los modelos de oleaje son cuatro, de tres casas independientes: EWAM y
    GWAM (DWD aleman), MFWAM (MeteoFrance, via Copernicus) y ECMWF WAM (centro
    europeo). Cuando varios coinciden, mas fiable la prevision. No requiere
    clave de API.

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
    combinando los cuatro modelos y recomendando neopreno segun la temperatura
    del agua.

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

import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

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
    # Orientacion de la playa: rumbo (grados) HACIA donde mira el mar abierto.
    # Sirve para clasificar el viento como offshore/onshore. Estimado por la
    # geografia de cada costa.
    facing_deg: float


SPOTS: list[Spot] = [
    Spot(
        name="Castelldefels",
        latitude=41.25,
        longitude=2.00,
        forecast_url="https://www.windguru.cz/201",
        facing_deg=155,   # mira al SSE
    ),
    Spot(
        name="Masnou",
        latitude=41.474775,
        longitude=2.305556,
        forecast_url="https://www.windguru.cz/501030",
        facing_deg=150,   # mira al SSE (costa del Maresme)
    ),
    Spot(
        name="Sitges",
        latitude=41.234065,
        longitude=1.820438,
        forecast_url="https://www.windguru.cz/48885",
        facing_deg=190,   # mira al S/SSW (la costa gira al sur)
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

# Fichero de estado para no repetir alertas identicas. Guarda, por spot, una
# "firma" de las ventanas ya avisadas. Solo se notifica si la firma cambia
# (ventana nueva, horario distinto o calidad distinta). En GitHub Actions se
# persiste entre ejecuciones via cache (ver el workflow). Si no existe (primera
# ejecucion), se asume que no se ha avisado nada todavia.
STATE_FILE: str = os.getenv("STATE_FILE", ".surf_state.json")
# Si se pone a "1", se ignora el estado y se notifica siempre (util para probar).
ALWAYS_NOTIFY: bool = os.getenv("ALWAYS_NOTIFY", "0") == "1"

# ---------------------------------------------------------------------------
# MODELOS DE OLEAJE
# ---------------------------------------------------------------------------
# Cuatro modelos de oleaje de tres casas independientes, para un consenso mas
# fiable. Cuando varios coinciden, mas confianza en la prevision.
#   "ewam"            -> DWD EWAM: Europa, 5 km. La mejor resolucion local.
#   "gwam"            -> DWD GWAM: global, 25 km. Hermano global del EWAM.
#   "meteofrance_wave"-> MeteoFrance MFWAM: global, ~8 km (via Copernicus).
#   "ecmwf_wam"       -> ECMWF WAM: global, 9 km. Casa independiente (el centro
#                        europeo, referencia mundial en prevision).
# Nota: EWAM y GWAM comparten origen (DWD/ICON Wave); MFWAM y ECMWF aportan
# opiniones verdaderamente independientes, que es lo que mejora el consenso.
MODELS: dict[str, str] = {
    "EWAM": "ewam",
    "GWAM": "gwam",
    "MFWAM": "meteofrance_wave",
    "ECMWF": "ecmwf_wam",
}

# Peso de fiabilidad de cada modelo para la media ponderada de altura de ola.
# Doblamos los dos modelos con mejor criterio para esta costa:
#   - EWAM: mayor resolucion (5 km), el mas fino para el Mediterraneo local.
#   - ECMWF: el centro europeo, referencia mundial en fiabilidad.
# Dejamos a 1 los secundarios (MFWAM solido pero sin destacar; GWAM es la
# version basta de EWAM, 25 km). Editable si quieres recalibrar.
MODEL_WEIGHTS: dict[str, float] = {
    "EWAM": 2.0,
    "ECMWF": 2.0,
    "MFWAM": 1.0,
    "GWAM": 1.0,
}

# Endpoints de Open-Meteo.
MARINE_API_URL: str = "https://marine-api.open-meteo.com/v1/marine"
FORECAST_API_URL: str = "https://api.open-meteo.com/v1/forecast"

# Variables de oleaje que pedimos a la Marine API POR MODELO (EWAM/GWAM).
# OJO: la temperatura del agua (sea_surface_temperature) NO la traen EWAM ni
# GWAM (solo dan oleaje). La pedimos aparte, sin forzar modelo, mas abajo.
MARINE_HOURLY_VARS: str = (
    "wave_height,wave_period,wave_direction,"
    "swell_wave_height,swell_wave_period,swell_wave_direction,"
    "wind_wave_height"
)
# Variable de temperatura del agua. Se pide SIN forzar modelo, para que
# Open-Meteo use su "best match" (MeteoFrance), que es quien provee la SST.
MARINE_SST_VAR: str = "sea_surface_temperature"
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
    modelo de oleaje):
      - wind_map: viento horario por timestamp ISO (de la Forecast API).
      - daylight_by_date: por fecha, (inicio_luz, fin_luz) con margen aplicado.
      - water_temp_map: temperatura del agua por timestamp ISO (de la Marine
        API sin forzar modelo; la SST la provee MeteoFrance, no EWAM/GWAM).
    Si una llamada falla, su estructura queda vacia (criterio conservador).
    """
    wind_map: dict[str, tuple[float | None, float | None]] = field(default_factory=dict)
    daylight_by_date: dict[str, tuple[datetime, datetime]] = field(default_factory=dict)
    water_temp_map: dict[str, float | None] = field(default_factory=dict)


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
    swell_direction: float | None       # Direccion de donde viene el swell (grados)
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
    Devuelve una recomendacion de neopreno en INGLES (solo la prenda, sin
    repetir la temperatura), pensada para una sesion larga de 2-3 h. Si no hay
    dato, devuelve cadena vacia (el llamador lo gestiona).
    """
    if water_temp is None:
        return ""

    t = water_temp
    if t >= 24:
        return "rashguard or no wetsuit"
    if t >= 22:
        return "2 mm shorty"
    if t >= 19:
        return "3/2 mm wetsuit"
    if t >= 16:
        return "4/3 mm + boots"
    if t >= 13:
        return "5/4 mm, boots & hood"
    return "5/4 mm with hood, gloves & boots"


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

    # --- Temperatura del agua (SST) ---
    # Se pide a la Marine API SIN forzar modelo, para que use "best match"
    # (MeteoFrance), que es quien provee la SST. EWAM/GWAM no la traen.
    sst_params = {
        "latitude": spot.latitude,
        "longitude": spot.longitude,
        "hourly": MARINE_SST_VAR,
        "forecast_days": 4,
        "timezone": TIMEZONE,
        "cell_selection": "sea",
    }
    sst_label = f"{spot.name}/sst"
    try:
        log.info("[%s] Consultando temperatura del agua...", sst_label)
        sst_payload = _request_with_retries(MARINE_API_URL, sst_params, sst_label)
        sst_hourly = sst_payload.get("hourly", {})
        sst_times = sst_hourly.get("time", [])
        sst_vals = sst_hourly.get("sea_surface_temperature", [])
        for i, t in enumerate(sst_times):
            aux.water_temp_map[t] = _safe_get(sst_vals, i)
        con_dato = sum(1 for v in aux.water_temp_map.values() if v is not None)
        log.info("[%s] Temperatura del agua: %d franjas con dato.", sst_label, con_dato)
    except Exception as e:
        log.warning("[%s] No se pudo obtener temperatura del agua (no critico): %s", sst_label, e)

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
    h_swell_d = hourly.get("swell_wave_direction", [])
    h_wind_w = hourly.get("wind_wave_height", [])
    # La temperatura del agua NO se lee aqui: viene del mapa de aux (SST se
    # pide aparte, sin forzar modelo, porque EWAM/GWAM no la traen).

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
        water_temp = aux.water_temp_map.get(t)

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
            swell_direction=_safe_get(h_swell_d, i),
            wind_wave_height=_safe_get(h_wind_w, i),
            water_temp=water_temp,
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

def now_local() -> datetime:
    """
    Hora actual en la zona horaria configurada (TIMEZONE), devuelta como
    datetime NAIVE (sin tzinfo).

    Por que naive: Open-Meteo, con timezone=Europe/Madrid, devuelve los
    timestamps en hora LOCAL de Madrid pero SIN marca de zona horaria. Para
    compararlos correctamente necesitamos un "ahora" tambien en hora de Madrid
    y tambien naive. Si usaramos datetime.now() a secas, en el runner de GitHub
    (que va en UTC) tendriamos un desfase de 1-2 horas y la ventana de busqueda
    quedaria corrida. Esta funcion resuelve ese bug.
    """
    return datetime.now(ZoneInfo(TIMEZONE)).replace(tzinfo=None)


def get_search_start(reference: datetime | None = None) -> datetime:
    """
    Devuelve el momento a partir del cual buscamos ventanas: AHORA (hora local
    del spot) mas el tiempo de antelacion (LEAD_TIME_HOURS), redondeado hacia
    arriba a la hora en punto (los datos de Open-Meteo son horarios).
    """
    ref = reference or now_local()
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


def representative_water_temp(aux: AuxiliaryData, reference: datetime | None = None) -> float | None:
    """
    Temperatura del agua representativa para el spot: la del primer timestamp
    futuro con dato (la mas cercana a la ventana de busqueda). Se lee del mapa
    de datos auxiliares (la SST se pide sin forzar modelo).
    """
    start = get_search_start(reference)
    # Recorremos los timestamps ordenados buscando el primero futuro con dato.
    for t in sorted(aux.water_temp_map.keys()):
        try:
            tdt = datetime.fromisoformat(t)
        except ValueError:
            continue
        if tdt >= start and aux.water_temp_map[t] is not None:
            return aux.water_temp_map[t]
    # Si no hay nada futuro, devolvemos cualquier dato disponible.
    for v in aux.water_temp_map.values():
        if v is not None:
            return v
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


def _wind_arrow(wind_from_deg: float | None) -> str:
    """
    Flecha que apunta HACIA donde sopla el viento (no de donde viene).
    Si el viento viene del norte (0), sopla hacia el sur, flecha hacia abajo.
    Usa 8 direcciones.
    """
    if wind_from_deg is None:
        return ""
    wind_to = (wind_from_deg + 180) % 360
    arrows = ["↑", "↗", "→", "↘", "↓", "↙", "←", "↖"]
    idx = int((wind_to + 22.5) % 360 / 45)
    return arrows[idx]


def classify_wind(beach_facing_deg: float, wind_from_deg: float | None) -> str:
    """
    Clasifica el viento respecto a la orientacion de la playa:
      - offshore : sopla de tierra a mar (peina la ola, ideal).
      - cross-off: lateral con componente de tierra (aceptable).
      - cross-on : lateral con componente de mar (regular).
      - onshore  : sopla de mar a tierra (deshace la ola, malo).
    Devuelve "" si no hay dato de viento.

    Metodo: comparamos HACIA donde sopla el viento con HACIA donde mira la
    playa (su mar abierto). Si coinciden -> offshore; si son opuestos -> onshore.
    """
    if wind_from_deg is None:
        return ""
    wind_to = (wind_from_deg + 180) % 360
    diff = abs((wind_to - beach_facing_deg + 180) % 360 - 180)
    if diff <= 45:
        return "offshore"
    if diff <= 90:
        return "cross-off"
    if diff <= 135:
        return "cross-on"
    return "onshore"


def compute_stars(
    height_max: float,
    swell_period: float | None,
    wind_kmh: float | None,
    wind_class: str,
    n_models_agree: int,
) -> int:
    """
    Calcula la calidad de una ventana en estrellas (1-5), calibrado para el
    Mediterraneo (swell debil): 5 estrellas no es un dia de oceano, es un dia
    notable PARA ESTA COSTA.

    Suma puntos de 4 factores (maximo teorico 5.5):
      - Tamano (0-2): lo primero, sin tamano no hay sesion.
      - Periodo del swell (0-1.5): la energia/calidad de la ola.
      - Viento (0-1.5): OPCION DURA, onshore penaliza a 0.
      - Consenso de modelos (0-0.5): cuantos de los 4 modelos coinciden en la
        ventana. Mas modelos de acuerdo = prevision mas fiable.

    'n_models_agree' es cuantos modelos respaldan la ventana (1 a 4).

    5 estrellas es RARO Y ESPECIAL: exige >=5.0 puntos Y tamano real (>=1.0m).
    Un dia pequeno, por perfecto que este, tope en 4 estrellas.
    """
    pts = 0.0

    # Tamano (0-2).
    if height_max >= 1.2:
        pts += 2.0
    elif height_max >= 1.0:
        pts += 1.5
    elif height_max >= 0.8:
        pts += 1.0
    else:
        pts += 0.5

    # Periodo del swell (0-1.5).
    sp = swell_period if swell_period is not None else 0.0
    if sp >= 6:
        pts += 1.5
    elif sp >= 5:
        pts += 1.0
    elif sp >= 4:
        pts += 0.5

    # Viento (0-1.5). Opcion dura: onshore = 0.
    clase_pts = {"offshore": 1.0, "cross-off": 0.6, "cross-on": 0.3, "onshore": 0.0}
    p = clase_pts.get(wind_class, 0.3)
    if wind_kmh is not None and wind_kmh < 12:
        p += 0.5
    pts += min(p, 1.5)

    # Consenso de modelos (0-0.5), graduado por cuantos coinciden de los 4:
    #   4 modelos -> +0.5 · 3 -> +0.4 · 2 -> +0.25 · 1 -> +0.0
    consenso_pts = {4: 0.5, 3: 0.4, 2: 0.25}.get(n_models_agree, 0.0)
    pts += consenso_pts

    # Mapeo. 5 estrellas raro: umbral alto Y tamano real.
    if pts >= 5.0 and height_max >= 1.0:
        return 5
    if pts >= 3.5:
        return 4
    if pts >= 2.5:
        return 3
    if pts >= 1.5:
        return 2
    return 1


def _stars_str(n: int) -> str:
    """Cadena visual de estrellas: llenas + vacias hasta 5."""
    return "★" * n + "☆" * (5 - n)


# Dias de la semana en ingles abreviados (datetime.weekday(): 0 = lunes).
_WEEKDAYS_EN = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


@dataclass
class _Window:
    """
    Representacion intermedia de una ventana surfeable, ya resumida y lista
    para pintar. Agrupa una o varias rachas (de uno o varios modelos) que se
    solapan en el tiempo el mismo dia.
    """
    start: datetime
    end: datetime
    h_min: float
    h_max: float
    p_min: float
    p_max: float
    wind_kmh: float | None
    wind_dir: float | None
    wave_dir: float | None
    swell_dir: float | None       # direccion de donde viene el swell de fondo
    swell_period: float | None    # periodo propio del swell de fondo
    quality: str                  # "limpio" / "picado" / "mixto"
    models: set[str]              # modelos que la respaldan
    facing_deg: float             # orientacion de la playa (para offshore/onshore)
    # Altura representativa (max de la racha) que aporta CADA modelo, para poder
    # hacer la media ponderada por fiabilidad. {modelo: altura_max}.
    height_by_model: dict[str, float] = field(default_factory=dict)


def _streak_to_window(streak: list[SurfSlot], model: str, facing_deg: float) -> _Window:
    """Convierte una racha cruda en una _Window resumida."""
    heights = [s.wave_height for s in streak]
    periods = [s.wave_period for s in streak]
    winds = [s.wind_speed for s in streak if s.wind_speed is not None]
    swell_periods = [s.swell_period for s in streak if s.swell_period is not None]
    labels = [s.quality_label() for s in streak]

    if labels.count("limpio") >= labels.count("picado"):
        quality = "limpio" if labels.count("limpio") >= labels.count("mixto") else "mixto"
    else:
        quality = "picado"

    mid = len(streak) // 2
    return _Window(
        start=streak[0].dt,
        end=streak[-1].dt,
        h_min=min(heights),
        h_max=max(heights),
        p_min=min(periods),
        p_max=max(periods),
        wind_kmh=(sum(winds) / len(winds)) if winds else None,
        wind_dir=streak[mid].wind_direction,
        wave_dir=streak[mid].wave_direction,
        swell_dir=streak[mid].swell_direction,
        swell_period=(sum(swell_periods) / len(swell_periods)) if swell_periods else None,
        quality=quality,
        models={model},
        facing_deg=facing_deg,
        height_by_model={model: max(heights)},
    )


def _overlaps(a: _Window, b: _Window) -> bool:
    """True si dos ventanas se solapan en el tiempo (mismo evento de mar)."""
    return a.start <= b.end and b.start <= a.end


def _merge_windows(a: _Window, b: _Window) -> _Window:
    """Fusiona dos ventanas solapadas, uniendo rangos y modelos."""
    a_larga = (a.end - a.start) >= (b.end - b.start)
    # Altura por modelo: si un modelo aparece en ambas, nos quedamos con su
    # maximo (no sobrescribimos), para no perder informacion en la ponderada.
    hbm = dict(a.height_by_model)
    for model, h in b.height_by_model.items():
        hbm[model] = max(hbm.get(model, h), h)
    return _Window(
        start=min(a.start, b.start),
        end=max(a.end, b.end),
        h_min=min(a.h_min, b.h_min),
        h_max=max(a.h_max, b.h_max),
        p_min=min(a.p_min, b.p_min),
        p_max=max(a.p_max, b.p_max),
        # Viento y direcciones: nos quedamos con los de la ventana mas larga.
        wind_kmh=a.wind_kmh if a_larga else b.wind_kmh,
        wind_dir=a.wind_dir if a_larga else b.wind_dir,
        wave_dir=a.wave_dir if a_larga else b.wave_dir,
        swell_dir=a.swell_dir if a_larga else b.swell_dir,
        swell_period=a.swell_period if a_larga else b.swell_period,
        # Calidad: si alguna es "picado", lo reflejamos (mas conservador).
        quality="picado" if "picado" in (a.quality, b.quality) else (
            "limpio" if "limpio" in (a.quality, b.quality) else "mixto"
        ),
        models=a.models | b.models,
        facing_deg=a.facing_deg,
        height_by_model=hbm,
    )


def _collect_and_merge_windows(result: SpotResult) -> list[_Window]:
    """
    Toma todas las rachas de todos los modelos del spot, las convierte en
    _Window, y fusiona las que se solapan en el tiempo (aunque vengan de
    modelos distintos). Devuelve la lista final ordenada cronologicamente.

    Usa el algoritmo estandar de fusion de intervalos: ordenar por inicio y
    fusionar cada ventana con el acumulador si se solapa. Esto fusiona
    correctamente cadenas A-B-C (A solapa B, B solapa C, aunque A no toque C),
    cosa que la version anterior (parar en la primera coincidencia) no hacia.
    """
    facing = result.spot.facing_deg
    raw: list[_Window] = []
    for model_label, streaks in result.streaks_by_model.items():
        for streak in streaks:
            raw.append(_streak_to_window(streak, model_label, facing))

    if not raw:
        return []

    raw.sort(key=lambda w: w.start)
    merged: list[_Window] = [raw[0]]
    for w in raw[1:]:
        if _overlaps(merged[-1], w):
            merged[-1] = _merge_windows(merged[-1], w)
        else:
            merged.append(w)

    return merged


def _weighted_height(w: _Window) -> float | None:
    """
    Media ponderada por fiabilidad de la altura de ola entre los modelos que
    respaldan la ventana. Cada modelo aporta su altura (max de su racha)
    multiplicada por su peso de MODEL_WEIGHTS. Si no hay datos, None.
    """
    if not w.height_by_model:
        return None
    num = 0.0
    den = 0.0
    for model, h in w.height_by_model.items():
        peso = MODEL_WEIGHTS.get(model, 1.0)
        num += peso * h
        den += peso
    return num / den if den > 0 else None


def _fmt_height(w: _Window) -> str:
    """
    Rango envolvente de altura (min-max entre modelos) MAS el valor central
    ponderado por fiabilidad como referencia. Ej: "0.9–1.1 m (~1.05)".
    El rango avisa de la dispersion; el central es la mejor estimacion.
    """
    central = _weighted_height(w)
    # Rango envolvente.
    if w.h_max - w.h_min < 0.1:
        rango = f"{w.h_max:.1f} m"
        # Si el rango es estrecho, el central no aporta; lo omitimos.
        return rango
    rango = f"{w.h_min:.1f}–{w.h_max:.1f} m"
    if central is not None:
        return f"{rango} (~{central:.1f})"
    return rango


def _fmt_period(w: _Window) -> str:
    """Rango de periodo de la ola total."""
    if round(w.p_min) == round(w.p_max):
        return f"{w.p_max:.0f} s"
    return f"{w.p_min:.0f}–{w.p_max:.0f} s"


def _fmt_swell(w: _Window) -> str:
    """Direccion y periodo del swell de fondo (ej. 'SW · 5.3 s')."""
    parts = []
    if w.swell_dir is not None:
        parts.append(_degrees_to_compass(w.swell_dir))
    if w.swell_period is not None:
        parts.append(f"{w.swell_period:.1f} s")
    if not parts:
        return "n/a"
    return " · ".join(parts)


def _fmt_wind(w: _Window) -> str:
    """Viento: velocidad, direccion, flecha y clase (offshore/onshore...)."""
    if w.wind_kmh is None:
        return "n/a"
    compass = _degrees_to_compass(w.wind_dir)
    arrow = _wind_arrow(w.wind_dir)
    wind_class = classify_wind(w.facing_deg, w.wind_dir)
    base = f"{w.wind_kmh:.0f} km/h {compass}"
    if arrow:
        base += f" {arrow}"
    if wind_class:
        base += f" {wind_class}"
    return base


def _fmt_sea(w: _Window) -> str:
    """Estado del mar en ingles."""
    return {"limpio": "clean", "picado": "choppy", "mixto": "mixed"}.get(w.quality, w.quality)


def _fmt_models(w: _Window) -> str:
    """
    Modelos que respaldan la ventana, en el orden de MODELS. Si coinciden los
    cuatro, lo resumimos como "all 4 models" para no alargar la linea.
    """
    total = len(MODELS)
    n = len(w.models)
    if n >= total:
        return f"all {total} models"
    # Listar en el orden canonico de MODELS los que esten presentes.
    presentes = [m for m in MODELS if m in w.models]
    if n == 1:
        return f"{presentes[0]} only"
    return " + ".join(presentes)


def _window_stars(w: _Window) -> int:
    """
    Estrellas de calidad de una ventana. Usa la altura PONDERADA por
    fiabilidad (no el maximo optimista), para que un solo modelo alegre no
    infle la nota.
    """
    wind_class = classify_wind(w.facing_deg, w.wind_dir)
    height = _weighted_height(w)
    if height is None:
        height = w.h_max  # fallback defensivo
    return compute_stars(height, w.swell_period, w.wind_kmh, wind_class, len(w.models))


def _verdict(stars: int) -> str:
    """Veredicto-titular en ingles segun las estrellas."""
    return {
        5: "Epic window",
        4: "Great window",
        3: "Good window",
        2: "Rideable",
        1: "Marginal",
    }.get(stars, "Window")


def _day_label_en(dt: datetime) -> str:
    """Etiqueta de dia en ingles (Today / Tomorrow / Wed 04/06)."""
    today = now_local().date()
    if dt.date() == today:
        return "Today"
    if dt.date() == today + timedelta(days=1):
        return "Tomorrow"
    return f"{_WEEKDAYS_EN[dt.weekday()]} {dt:%d/%m}"


def _fmt_water(temp: float | None) -> str:
    """Linea de agua + neopreno en ingles."""
    if temp is None:
        return "Water n/a · bring your usual suit"
    suit = wetsuit_recommendation(temp)
    return f"Water {temp:.0f}° · {suit}" if suit else f"Water {temp:.0f}°"


def _aligned(label: str, value: str, width: int = 8) -> str:
    """Fila etiqueta-valor alineada en columnas (estilo Apple)."""
    return f"{label:<{width}}{value}"


def _window_detail_block(w: _Window) -> list[str]:
    """
    Bloque de detalle de UNA ventana en formato columnas alineadas.
    Se envuelve en monoespaciado (```) para que las columnas cuadren en
    Telegram.
    """
    return [
        _aligned("Waves", _fmt_height(w)),
        _aligned("Period", _fmt_period(w)),
        _aligned("Swell", _fmt_swell(w)),
        _aligned("Wind", _fmt_wind(w)),
        _aligned("Sea", _fmt_sea(w)),
        _aligned("Models", _fmt_models(w)),
    ]


def build_spot_message(result: SpotResult) -> str:
    """
    Construye el mensaje de Telegram para UN spot (Propuesta A): cabecera con
    veredicto y estrellas, detalle en columnas alineadas estilo Apple, en
    ingles. Incluye direccion/periodo del swell y viento offshore/onshore.
    """
    spot = result.spot
    windows = _collect_and_merge_windows(result)

    if not windows:
        return f"*{spot.name}*\nSurfable conditions detected.\n{spot.forecast_url}"

    temp = result.water_temp

    # --- UNA SOLA VENTANA ---
    if len(windows) == 1:
        w = windows[0]
        stars = _window_stars(w)
        day = _day_label_en(w.start)
        lines = [
            f"*{spot.name}*",
            f"{_verdict(stars)} · {_stars_str(stars)}",
            "",
            f"{day} · {w.start:%H:%M}–{w.end:%H:%M}  ({_window_hours(w)}h)",
            "```",
            *_window_detail_block(w),
            "```",
            _fmt_water(temp),
            "",
            f"[View full forecast]({spot.forecast_url})",
        ]
        return "\n".join(lines)

    # --- VARIAS VENTANAS ---
    # Veredicto global = el de la mejor ventana.
    best_stars = max(_window_stars(w) for w in windows)
    header = [
        f"*{spot.name}*",
        f"{_verdict(best_stars)} · {len(windows)} windows · best {_stars_str(best_stars)}",
        "",
    ]

    body: list[str] = []
    current_day = None
    for w in windows:
        day = _day_label_en(w.start)
        if day != current_day:
            current_day = day
            if body:
                body.append("")
            body.append(f"*{day}*")
        stars = _window_stars(w)
        body.append(f"{w.start:%H:%M}–{w.end:%H:%M} ({_window_hours(w)}h)  {_stars_str(stars)}")
        body.append("```")
        body.extend(_window_detail_block(w))
        body.append("```")

    footer = [
        _fmt_water(temp),
        "",
        f"[View full forecast]({spot.forecast_url})",
    ]
    return "\n".join(header + body + footer)


def _window_hours(w: _Window) -> int:
    """Duracion de la ventana en horas (franjas horarias)."""
    return int(round((w.end - w.start).total_seconds() / 3600)) + 1


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
# ESTADO ANTI-DUPLICADOS
# ---------------------------------------------------------------------------
# Para no repetir el mismo aviso cada 6 horas, guardamos por spot una "firma"
# de las ventanas ya notificadas. Solo se vuelve a avisar de un spot si su
# firma cambia (aparece una ventana nueva, cambia el horario o cambia la
# calidad en estrellas). El estado se persiste en un fichero JSON que GitHub
# Actions cachea entre ejecuciones.

def _spot_signature(result: SpotResult) -> str:
    """
    Firma del conjunto de ventanas de un spot. Se basa en, por cada ventana,
    su dia, hora de inicio y fin, y sus estrellas. Asi, si el horario o la
    calidad cambian, la firma cambia y se vuelve a avisar; si todo sigue igual,
    la firma se mantiene y no se repite el mensaje.
    """
    windows = _collect_and_merge_windows(result)
    partes = []
    for w in sorted(windows, key=lambda x: x.start):
        stars = _window_stars(w)
        partes.append(f"{w.start:%Y-%m-%dT%H}|{w.end:%H}|{stars}")
    return ";".join(partes)


def load_alert_state(path: str) -> dict[str, str]:
    """
    Carga el estado de alertas (firma por spot) desde el fichero JSON.
    Si no existe o esta corrupto, devuelve un estado vacio (primera ejecucion).
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
    except FileNotFoundError:
        log.info("[estado] No hay estado previo (primera ejecucion).")
    except (json.JSONDecodeError, OSError) as e:
        log.warning("[estado] No se pudo leer el estado (%s); se asume vacio.", e)
    return {}


def save_alert_state(path: str, state: dict[str, str]) -> None:
    """Guarda el estado de alertas (firma por spot) en el fichero JSON."""
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        log.info("[estado] Estado guardado (%d spots).", len(state))
    except OSError as e:
        log.warning("[estado] No se pudo guardar el estado: %s", e)


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

    result.water_temp = representative_water_temp(aux)

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

    # Estado anti-duplicados: firma de las ventanas ya avisadas por spot.
    state = {} if ALWAYS_NOTIFY else load_alert_state(STATE_FILE)
    new_state: dict[str, str] = dict(state)

    messages_sent = 0
    spots_with_window = 0
    spots_skipped_dup = 0

    for spot in SPOTS:
        log.info("--- Evaluando spot: %s ---", spot.name)
        try:
            result = evaluate_spot(spot)
        except Exception as e:
            log.error("[%s] Error evaluando el spot: %s", spot.name, e)
            continue

        if not result.has_window():
            log.info("[%s] Sin ventana surfeable; no se notifica.", spot.name)
            # Si el spot dejo de tener ventanas, limpiamos su firma para que un
            # futuro repunte vuelva a avisar.
            new_state.pop(spot.name, None)
            continue

        spots_with_window += 1
        signature = _spot_signature(result)

        # Si la firma coincide con la ya avisada, no repetimos.
        if not ALWAYS_NOTIFY and state.get(spot.name) == signature:
            log.info("[%s] Ventana ya avisada (sin cambios); no se repite.", spot.name)
            spots_skipped_dup += 1
            continue

        message = build_spot_message(result)
        if send_telegram_message(message):
            messages_sent += 1
            new_state[spot.name] = signature  # registrar solo si se envio bien

    # Persistir el estado actualizado (salvo en modo ALWAYS_NOTIFY).
    if not ALWAYS_NOTIFY:
        save_alert_state(STATE_FILE, new_state)

    log.info(
        "=== Fin. %d spot(s) con ventana, %d mensaje(s) enviado(s), "
        "%d sin cambios (omitidos). ===",
        spots_with_window, messages_sent, spots_skipped_dup,
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
