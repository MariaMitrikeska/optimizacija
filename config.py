"""
================================================================================
 CONFIG.PY — Сите параметри на проектот на едно место
================================================================================
 Зошто постои овој фајл?
   Наместо бројки да бидат расфрлани низ кодот, сè што може да се менува
   (цени, тарифи, локација...) е ТУКА. Ако EVN смени тарифа — менуваш еден ред.
================================================================================
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)

LATITUDE = 41.9981
LONGITUDE = 21.4254
TIMEZONE = "Europe/Skopje"

PV_KWP = 5.0
PV_TILT = 30
PV_AZIMUTH = 0
PV_LOSS = 14

VT_BLOKOVI = [
    (210,   5.0502),
    (630,   6.3348),
    (1050,  8.4573),
    (None, 20.8300),
]
NT_CENA = 2.2493
MREZARINA = 2.0339
FEED_IN = 1.50

VT_UDEL = 0.571

BIZNIS_CENA = 17.2833
BIZNIS_MREZARINA = 0.7167

BATERII_BIZNIS = {
    20:  350510,
    40:  701026,
    60:  1051540,
    80:  1402052,
    120: 2103078,
}

VT_CASOVI = list(range(7, 13)) + list(range(15, 22))

BATERII = {
    5:   66500,
    10: 126000,
    16: 141450,
    20: 252000,
    32: 282900,
}

_BAZA = "https://akumulatori.mk/felicity-solar-%D0%BB%D0%B8%D1%82%D0%B8%D1%83%D0%BC-"
KATALOG_URL = "https://akumulatori.mk/felicity-solar"

BATERII_LINKOVI = {
    5:  _BAZA + "5-kwh-48-v",
    10: _BAZA + "10-kwh-48-v-2",
    16: KATALOG_URL,
    20: _BAZA + "20-kwh-48-v",
    32: KATALOG_URL,
}

for _kap in BATERII:
    BATERII_LINKOVI.setdefault(_kap, KATALOG_URL)

BATERII_MODELI = {
    5:  "5.12 kWh 48V",
    10: "10 kWh 48V",
    16: "16 kWh 48V",
    20: "20 kWh (2× 10 kWh)",
    32: "32 kWh (2× 16 kWh)",
}
for _kap in BATERII:
    BATERII_MODELI.setdefault(_kap, f"{_kap} kWh LFP")
BATERIJA_EFIKASNOST = 0.90
BATERIJA_MIN_SOC = 0.10
BATERIJA_C_RATE = 0.5

DOZVOLI_POLNENJE_OD_MREZA = True


PV_CENI_EUR = {
    3:      2400,
    5:      3500,
    7:      4500,
    10:     6400,
    12:     7500,
}

PV_MAX_KWP_DOMAKINSTVO = 12.0
INVERTOR_MAX_KW = 10.0

PV_CENI_BIZNIS_EUR = {
    20:    11800,
    30:    17100,
    50:    27500,
    100:   53000,
}

PV_PRINOS_KWH_PO_KWP = 1100

GREENJE_FAKTOR = {
    "struja":    2.2,
    "toplinska": 1.6,
    "drva":      1.1,
}

RANDOM_SEED = 42

DISKONT = 0.05
RAST_NA_STRUJA = 0.025
ZIVOTEN_VEK = 15
MKD_PER_EUR = 61.5
