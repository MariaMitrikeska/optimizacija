"""
================================================================================
 PODATOCI.PY — Чекор 1: Земање на податоците
================================================================================
 Овде се собираат ДВАТА влезни податоци што му требаат на целиот систем:

   1. СОНЦЕ (PVGIS) — колку струја произведуваат панелите, час по час
      Извор: PVGIS — сателитска база на Европската Комисија. За Скопје,
      3 години историја (2021-2023), 26.000+ редови.

   2. ПОТРОШУВАЧКА (load профил) — колку струја троши куќата, час по час
      Се генерира реалистичен профил кој зависи од:
        - час во денот (пик наутро и навечер, ниско ноќе)
        - сезона (зима повеќе, лето со клима)
        - КАКО СЕ ГРЕЕ куќата (струја / топлинска пумпа / дрва)
================================================================================
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import requests

import config

PVGIS_URL = "https://re.jrc.ec.europa.eu/api/v5_3/seriescalc"
PVGIS_CSV = config.DATA / "pvgis_skopje.csv"

# Open-Meteo: бесплатна метеоролошка база (не бара клуч).
# Оттука ја земаме ОБЛАЧНОСТА — најважниот податок за соларна прогноза.
METEO_URL = "https://archive-api.open-meteo.com/v1/archive"
METEO_CSV = config.DATA / "vreme_skopje.csv"



# ==============================================================================
# 1. СОНЦЕ — податоци од PVGIS
# ==============================================================================
def zemi_pvgis() -> pd.DataFrame:
    """Врати табела со сончеви податоци за Скопје, час по час.

    Колони:
        pv_power_kw — колку kW произведува 5 kWp систем во тој час
        temp_air    — температура (важна и за потрошувачката — греење/ладење!)

    Првиот пат симнува од интернет (~10 сек) и зачувува во data/ (cache).
    Секој следен пат чита од диск — брзо и работи без интернет.
    """
    # --- Ако веќе имаме симнато → читај од диск (cache) ---
    if PVGIS_CSV.exists():
        df = pd.read_csv(PVGIS_CSV, index_col=0, parse_dates=True)
        # Подсигурај се дека index е UTC datetime
        df.index = pd.to_datetime(df.index, utc=True)
        if "pv_power_kw" not in df.columns and "pv_power_w" in df.columns:
            df["pv_power_kw"] = df["pv_power_w"] / 1000.0
        return df

    # --- Инаку: симни од PVGIS API ---
    params = {
        "lat": config.LATITUDE, "lon": config.LONGITUDE,
        "startyear": 2021, "endyear": 2023,
        "pvcalculation": 1,              # сакаме PV излез, не само радијација
        "peakpower": config.PV_KWP,      # 5 kWp референтен систем
        "loss": config.PV_LOSS,          # 14% загуби
        "angle": config.PV_TILT,         # 30° наклон
        "aspect": config.PV_AZIMUTH,     # кон југ
        "outputformat": "json",
    }
    resp = requests.get(PVGIS_URL, params=params, timeout=120)
    resp.raise_for_status()
    zapisi = resp.json()["outputs"]["hourly"]

    df = pd.DataFrame(zapisi)
    # PVGIS време е 'YYYYMMDD:HHMM' → претвори во вистински datetime (UTC)
    df["time"] = pd.to_datetime(df["time"], format="%Y%m%d:%H%M", utc=True)
    df["time"] = df["time"].dt.floor("h")    # порамни на почеток на час
    df = df.set_index("time").sort_index()
    df = df.rename(columns={"P": "pv_power_w", "T2m": "temp_air", "G(i)": "ghi"})
    df["pv_power_kw"] = df["pv_power_w"] / 1000.0

    df.to_csv(PVGIS_CSV)    # cache за следен пат
    return df


# ==============================================================================
# 1б. ОБЛАЧНОСТ — метеоролошки податоци од Open-Meteo
# ==============================================================================
def zemi_vreme() -> pd.DataFrame:
    """Врати табела со облачност и температура за Скопје, час по час.

    ЗОШТО НИ ТРЕБА ОБЛАЧНОСТА?
    ---------------------------
    Најголемиот непознат фактор за соларната продукција е — дали ќе биде
    облачно. Часот и сезоната се предвидливи (календар), но облаците не се.
    Без овој податок, моделот погодува само „ноќе 0, пладне многу" — што
    не е вистинско учење.

    ВАЖНО: ова НЕ е data leakage. Облачноста доаѓа од метеоролошка прогноза,
    која ја имаме однапред за утре. (За разлика од измерената PV продукција,
    која не ја знаеме додека не се случи.)

    Колони:
        cloud_cover — % облачност (0 = ведро, 100 = целосно облачно)
        wind_speed  — брзина на ветар (ги лади панелите → подобра ефикасност)
    """
    # --- Cache: ако веќе сме симнале, читај од диск ---
    if METEO_CSV.exists():
        df = pd.read_csv(METEO_CSV, index_col=0, parse_dates=True)
        df.index = pd.to_datetime(df.index, utc=True)
        # Земи само колоните што ни требаат и што ги НЕМА веќе во PVGIS
        # (wind_speed и temp_air ги има и PVGIS → не ги дуплираме)
        #
        # cloud_low/mid/high се одделно затоа што НИСКИТЕ облаци го
        # блокираат сонцето многу повеќе од високите (перјести) облаци.
        kolonite = [c for c in ("cloud_cover", "cloud_low", "cloud_mid",
                                "cloud_high", "humidity", "precip")
                    if c in df.columns]
        return df[kolonite]

    # --- Симни од Open-Meteo (бесплатно, без API клуч) ---
    resp = requests.get(METEO_URL, params={
        "latitude": config.LATITUDE,
        "longitude": config.LONGITUDE,
        "start_date": "2021-01-01",
        "end_date": "2023-12-31",
        "hourly": "cloud_cover,wind_speed_10m",
        "timezone": "UTC",
    }, timeout=120)
    resp.raise_for_status()

    h = resp.json()["hourly"]
    df = pd.DataFrame({
        "cloud_cover": h["cloud_cover"],
        "wind_speed": h["wind_speed_10m"],
    }, index=pd.to_datetime(h["time"], utc=True))
    df.index.name = "time"

    df.to_csv(METEO_CSV)   # cache за следен пат
    return df


# ==============================================================================
# 2. ПОТРОШУВАЧКА — реалистичен профил на македонска куќа
# ==============================================================================
def napravi_load_profil(
    index: pd.DatetimeIndex,
    temp: pd.Series,
    godisen_kwh: float = 10000,
    greenje: str = "struja",
) -> pd.Series:
    """Генерирај колку kWh троши куќата во секој час.

    Како е изградено (секој дел одговара на реално однесување):

    1. ДНЕВНА КРИВА — луѓето наутро се будат (мал пик 7-9ч), преку ден
       куќата е полупразна, навечер сите се дома (голем пик 18-22ч),
       ноќе се спие (минимум).

    2. ГРЕЕЊЕ (зима) — кога надвор е студено (<15°C), се пали греењето.
       Колку струја троши зависи од ТИПОТ:
         - "struja"    → директни грејалки/инвертер: многу струја (фактор 2.2)
         - "toplinska" → топлинска пумпа е 3× поефикасна (фактор 1.6)
         - "drva"      → дрвата не се струја: минимален пораст (фактор 1.1)

    3. ЛАДЕЊЕ (лето) — кога е жешко (>26°C), се пали климата → повеќе струја.

    На крај целата крива се СКАЛИРА за да собере точно godisen_kwh годишно.
    """
    local = index.tz_convert(config.TIMEZONE)
    hour = local.hour.values
    temp_v = temp.values

    # --- 1. Основна дневна шема (24 вредности — релативна тежина на секој час)
    dnevna = np.array([
        0.5, 0.4, 0.4, 0.4, 0.4, 0.5,   # 00-05: ноќ, скоро сè изгаснато
        0.7, 1.0, 1.1, 0.9, 0.8, 0.8,   # 06-11: утрински пик (бојлер, кафе)
        0.9, 1.0, 0.9, 0.8, 0.9, 1.2,   # 12-17: ручек + попладне
        1.6, 1.9, 1.9, 1.7, 1.3, 0.8,   # 18-23: ВЕЧЕРЕН ПИК (вечера, ТВ, сите дома)
    ])
    baza = dnevna[hour]

    # --- 2. Греење: колку е постудено под 15°C, толку повеќе струја
    faktor = config.GREENJE_FAKTOR[greenje]
    greenje_dodatok = np.maximum(0, 15 - temp_v) / 15 * (faktor - 1.0) * baza

    # --- 3. Ладење: клима над 26°C
    ladenje_dodatok = np.maximum(0, temp_v - 26) / 10 * 0.6 * baza

    profil = baza + greenje_dodatok + ladenje_dodatok

    # --- 4. Скалирај: вкупната годишна сума да биде точно godisen_kwh
    godini = index.year.nunique()
    profil = profil * (godisen_kwh * godini / profil.sum())

    return pd.Series(profil, index=index, name="load_kwh")


# ==============================================================================
# 3. СЀ ЗАЕДНО — една функција што враќа комплетна табела
# ==============================================================================
def zemi_gi_site_podatoci(godisen_kwh=10000, greenje="struja") -> pd.DataFrame:
    """Главна функција: врати табела со СИТЕ податоци, час по час.

    Колони:
        pv_power_kw  — колку сонцето дава (PVGIS)
        temp_air     — температура (PVGIS)
        cloud_cover  — облачност % (Open-Meteo) ← клучна за ML прогнозата
        wind_speed   — ветар (Open-Meteo)
        load_kwh     — колку куќата троши (генериран профил)

    Ова е влезот и за ML моделот и за LP оптимизацијата.
    """
    df = zemi_pvgis()

    # Спој ја облачноста (ако Open-Meteo е достапен; ако не — продолжи без неа)
    try:
        vreme = zemi_vreme()
        df = df.join(vreme, how="left")
        # Ако некој час недостасува → пополни со најблиската вредност
        for kol in vreme.columns:
            if kol in df.columns:
                df[kol] = df[kol].ffill().bfill()
    except Exception as e:
        print(f"⚠️  Облачноста не е достапна ({type(e).__name__}) — "
              f"моделот ќе работи само со календарски features.")

    df["load_kwh"] = napravi_load_profil(
        df.index, df["temp_air"], godisen_kwh, greenje
    )
    return df


# --- Тест: пушти `python podatoci.py` да провериш дека сè работи ---
if __name__ == "__main__":
    df = zemi_gi_site_podatoci(10000, "struja")
    print(f"Редови: {len(df):,}")
    print(f"PV годишно (5 kWp): {df['pv_power_kw'].sum() / df.index.year.nunique():,.0f} kWh")
    print(f"Load годишно: {df['load_kwh'].sum() / df.index.year.nunique():,.0f} kWh")
    print(df[["pv_power_kw", "temp_air", "load_kwh"]].head())
