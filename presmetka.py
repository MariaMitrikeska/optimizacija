"""
================================================================================
 PRESMETKA.PY — Чекор 4: Која батерија е НАЈИСПЛАТЛИВА?
================================================================================
 Овој фајл го спојува сè:

   1. Од 4-те СМЕТКИ на корисникот (март/јуни/септ/дек) → колку kWh троши
      и во КОЈ EVN БЛОК спаѓа (важно: батеријата ги заменува најскапите kWh!)

   2. За СЕКОЈА батерија од понудата (5/10/20/30 kWh, реални цени):
      пушти LP оптимизација на 4 сезонски недели → годишна заштеда

   3. ЕКОНОМИКА: инвестиција → отплата → NPV → препорака

 Зошто 4 сезонски недели а не цела година?
   LP за цела година трае 5+ мин. Затоа: по 1 типична недела од секоја
   сезона × 52/4. Грешка < 5%, а трае < 60 сек. (валидирано)
================================================================================
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import config
from lp_optimizacija import optimalen_dispech, bez_baterija

SEZONSKI_NEDELI = {
    "zima":    "2023-01-16",
    "prolet":  "2023-04-10",
    "leto":    "2023-07-10",
    "esen":    "2023-10-09",
}


def ceni_po_cas(index: pd.DatetimeIndex, vt_cena: float,
                rezim: str = "domakinstvo") -> pd.Series:
    """За секој час: колку чини 1 kWh од EVN (тарифа + мрежарина).

    ДВА СОСЕМА РАЗЛИЧНИ РЕЖИМИ:

    1) ДОМАЌИНСТВО — ДВЕ тарифи:
         ВТ (скапо): 07-13 и 15-22, понеделник-сабота
         НТ (ефтино): ноќе 22-07, попладне 13-15, цела недела
       → батеријата заработува и преку арбитража (полни ефтино, празни скапо)

    2) ФИРМА („мали потрошувачи") — ЕДНА рамна тарифа:
         иста цена 24 часа, секој ден, без блокови
       → нема арбитража; батеријата заработува само преку само-потрошувачка
         на сопственото сонце (но цената е ~18 ден/kWh — доволно вредно)
    """
    if rezim == "biznis":
        cena = np.full(len(index), config.BIZNIS_CENA + config.BIZNIS_MREZARINA)
        return pd.Series(cena, index=index)

    local = index.tz_convert(config.TIMEZONE)
    vt = np.isin(local.hour, config.VT_CASOVI) & (local.dayofweek < 6)
    cena = np.where(vt, vt_cena, config.NT_CENA) + config.MREZARINA
    return pd.Series(cena, index=index)


def smetka_vo_kwh(mesecna_smetka: float) -> float:
    """Инверзна пресметка: од месечна сметка (МКД) → месечни kWh.

    Сметката се состои од: ВТ блокови (за ~50% од kWh) + НТ (50%) + мрежарина.
    Бараме kWh со бисекција (пробуваме сè додека не се совпадне).
    """
    def kolku_cini(m_kwh):
        vt_del = m_kwh * config.VT_UDEL
        nt_del = m_kwh * (1 - config.VT_UDEL)
        cost, prev, ostatok = 0.0, 0, vt_del
        for granica, cena in config.VT_BLOKOVI:
            g = granica if granica else float("inf")
            del_ = min(ostatok, g - prev)
            if del_ <= 0:
                break
            cost += del_ * cena
            ostatok -= del_
            prev = g
        return cost + nt_del * config.NT_CENA + m_kwh * config.MREZARINA

    lo, hi = 10.0, 10000.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if kolku_cini(mid) < mesecna_smetka:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def marginalen_blok(mesecen_vt_kwh: float) -> tuple[int, float]:
    """Во кој блок ЗАВРШУВА потрошувачката → тоа е цената што батеријата ја штеди.

    Пример: 800 kWh месечно во ВТ → последните kWh се во Блок 3 (8.4573).
    Батеријата ГИ ЗАМЕНУВА токму тие најскапи kWh!
    """
    granici = [(210, 1), (630, 2), (1050, 3), (float("inf"), 4)]
    ceni = {1: 5.0502, 2: 6.3348, 3: 8.4573, 4: 20.83}
    for granica, blok in granici:
        if mesecen_vt_kwh <= granica:
            return blok, ceni[blok]
    return 4, ceni[4]


def od_4_smetki(smetki: dict) -> tuple[float, dict, int, float]:
    """Од 4-те сезонски сметки → (годишен kWh, сезонски тежини, блок, ВТ цена).

    Зошто 4 сметки? Една сметка не кажува КОГА трошиш. Куќа што се грее
    на струја има декемвриска сметка 2-3× поголема од јунската — тоа
    драматично влијае колку батерија ѝ треба зиме vs лете.

    smetki = {"mart": 5000, "juni": 3000, "septemvri": 3500, "dekemvri": 9000}
    """
    sezona_mapa = {"mart": "prolet", "juni": "leto",
                   "septemvri": "esen", "dekemvri": "zima"}

    mesecni_kwh = {}
    for mesec, iznos in smetki.items():
        if iznos and iznos > 0:
            mesecni_kwh[sezona_mapa[mesec]] = smetka_vo_kwh(float(iznos))

    if not mesecni_kwh:
        raise ValueError("Барем една сметка мора да е внесена")

    prosek = np.mean(list(mesecni_kwh.values()))
    godisen_kwh = prosek * 12

    tezini = {s: kwh / prosek for s, kwh in mesecni_kwh.items()}
    for s in SEZONSKI_NEDELI:
        tezini.setdefault(s, 1.0)

    najgolem = max(mesecni_kwh.values())
    blok, vt_cena = marginalen_blok(najgolem * config.VT_UDEL)

    return godisen_kwh, tezini, blok, vt_cena


def testiraj_site_baterii(
    df: pd.DataFrame,
    godisen_kwh: float,
    pv_kwp: float,
    vt_cena: float,
    tezini: dict | None = None,
    kapaciteti: list | None = None,
    rezim: str = "domakinstvo",
) -> list[dict]:
    """За секоја батерија: LP на 4 сезонски недели → годишна заштеда → економија.

    Враќа листа од редови: капацитет, цена, заштеда, отплата, NPV,
    само-потрошувачка (% од PV енергијата искористена дома).
    """
    katalog = config.BATERII_BIZNIS if rezim == "biznis" else config.BATERII
    kapaciteti = kapaciteti or list(katalog.keys())

    godini = df.index.year.nunique()
    load_skala = godisen_kwh / (df["load_kwh"].sum() / godini)
    pv_skala = pv_kwp / config.PV_KWP

    profil_tezini = {}
    for sezona, start in SEZONSKI_NEDELI.items():
        s = pd.Timestamp(start, tz="UTC")
        profil_tezini[sezona] = float(df.loc[s: s + pd.Timedelta(hours=167), "load_kwh"].sum())
    prosek_profil = np.mean(list(profil_tezini.values()))
    profil_tezini = {k: v / prosek_profil for k, v in profil_tezini.items()}

    if tezini:
        korekcija = {s: tezini.get(s, 1.0) / profil_tezini[s] for s in SEZONSKI_NEDELI}
    else:
        korekcija = {s: 1.0 for s in SEZONSKI_NEDELI}

    def nedelna_presmetka(kapacitet):
        """Врати (годишен трошок, self-consumption %) за даден капацитет."""
        vkupno, izvoz, pv_suma = 0.0, 0.0, 0.0
        for sezona, start in SEZONSKI_NEDELI.items():
            s = pd.Timestamp(start, tz="UTC")
            w = df.loc[s: s + pd.Timedelta(hours=167)]
            load = w["load_kwh"] * load_skala * korekcija[sezona]
            pv = w["pv_power_kw"] * pv_skala
            ceni = ceni_po_cas(w.index, vt_cena, rezim)
            if kapacitet == 0:
                r = bez_baterija(load, pv, ceni, config.FEED_IN)
            else:
                r = optimalen_dispech(load, pv, ceni, config.FEED_IN, kapacitet)
            vkupno += r["trosok"]
            izvoz += r["izvoz_kwh"]
            pv_suma += float(pv.sum())
        self_pct = 100 * (1 - izvoz / pv_suma) if pv_suma > 0 else 0.0
        return vkupno / 4 * 52, self_pct

    baza, baza_self = nedelna_presmetka(0)

    def cena_za(kapacitet):
        """Реална цена од понудата, или проценка 17.526 МКД/kWh за меѓу-големини."""
        return katalog.get(kapacitet, round(kapacitet * 17526))

    rezultati = [{
        "kapacitet_kwh": 0, "cena_mkd": 0, "zasteda_godisno": 0,
        "otplata_godini": None, "npv_mkd": 0,
        "trosok_bez": round(baza), "trosok_so": round(baza),
        "self_pct": round(baza_self, 1),
    }]
    for kapacitet in kapaciteti:
        if kapacitet == 0:
            continue
        cena = cena_za(kapacitet)
        godisen_trosok, self_pct = nedelna_presmetka(kapacitet)
        zasteda = baza - godisen_trosok

        otplata = _otplata_so_rast(cena, zasteda)

        npv = sum(
            zasteda * (1 + config.RAST_NA_STRUJA) ** t / (1 + config.DISKONT) ** t
            for t in range(1, config.ZIVOTEN_VEK + 1)
        ) - cena

        rezultati.append({
            "kapacitet_kwh": kapacitet,
            "cena_mkd": cena,
            "zasteda_godisno": round(zasteda),
            "otplata_godini": round(otplata, 1) if otplata != float("inf") else None,
            "npv_mkd": round(npv),
            "trosok_bez": round(baza),
            "trosok_so": round(godisen_trosok),
            "self_pct": round(self_pct, 1),
        })
    return rezultati


def _otplata_so_rast(investicija: float, zasteda: float) -> float:
    """За колку години кумулативната заштеда ја стигнува инвестицијата
    (заштедата расте 2.5% годишно бидејќи струјата поскапува)."""
    if zasteda <= 1:
        return float("inf")
    kumulativno = 0.0
    for t in range(1, 41):
        godisna = zasteda * (1 + config.RAST_NA_STRUJA) ** (t - 1)
        if kumulativno + godisna >= investicija:
            return t - 1 + (investicija - kumulativno) / godisna
        kumulativno += godisna
    return float("inf")


def preporaka(rezultati: list[dict]) -> dict:
    """Избери ја најдобрата батерија: онаа со НАЈВИСОК NPV.

    (NPV ги комбинира и заштедата и цената — најчесен критериум во пракса)
    Редот со 0 kWh (без батерија) се прескокнува — тој е само референца.
    """
    kandidati = [r for r in rezultati if r["kapacitet_kwh"] > 0]
    return max(kandidati, key=lambda r: r["npv_mkd"])
