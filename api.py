"""
================================================================================
 API.PY — Чекор 5: Веб сервер (мостот меѓу браузерот и пресметките)
================================================================================
 Кога корисникот ќе кликне „Пресметај" во веб-страницата:

   Browser → JSON (сметки, греење, PV...) → ОВОЈ ФАЈЛ → presmetka.py
                                                              ↓
   Browser ← JSON (заштеди, отплата, препорака) ← ────────────┘

 Endpoints:
   GET  /            → ја сервира веб-страницата (index.html)
   POST /api/sizing  → главната пресметка
   GET  /api/health  → проверка дека серверот е жив

 Стартување:  python api.py  →  отвори http://127.0.0.1:5002/
================================================================================
"""
from __future__ import annotations

import logging
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

import config
from podatoci import zemi_gi_site_podatoci
from presmetka import od_4_smetki, testiraj_site_baterii, preporaka, smetka_vo_kwh, marginalen_blok

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("api")

ROOT = Path(__file__).parent
app = Flask(__name__, static_folder=str(ROOT), static_url_path="")
CORS(app)   # дозволи повици од browser (различен origin)

# Податоците се вчитуваат ЕДНАШ при стартување — по еден сет за секој тип
# греење (за да не се регенерира профилот на секое барање).
log.info("Вчитувам податоци (PVGIS + load профили)...")
PODATOCI = {g: zemi_gi_site_podatoci(10000, g) for g in ("struja", "toplinska", "drva")}
log.info("Готово: %d редови по профил", len(PODATOCI["struja"]))


@app.route("/")
def index():
    """Отвори ја веб-страницата."""
    return send_from_directory(str(ROOT), "index.html")


@app.route("/api/health")
def health():
    """Брза проверка дека серверот работи."""
    return jsonify({"status": "ok"})


@app.route("/api/ceni")
def ceni():
    """Ги враќа СИТЕ цени и тарифи од config.py на фронтендот.

    Зошто? За да има само ЕДЕН извор на вистина — ако смениш цена во
    config.py, автоматски се менува и во веб страницата. Без дуплирање.
    """
    return jsonify({
        "baterii": config.BATERII,
        "baterii_biznis": config.BATERII_BIZNIS,
        "baterii_linkovi": config.BATERII_LINKOVI,
        "baterii_modeli": config.BATERII_MODELI,
        "katalog_url": config.KATALOG_URL,
        "pv_ceni_eur": config.PV_CENI_EUR,
        "pv_ceni_biznis_eur": config.PV_CENI_BIZNIS_EUR,
        "pv_prinos": config.PV_PRINOS_KWH_PO_KWP,
        "pv_max_kwp": config.PV_MAX_KWP_DOMAKINSTVO,
        "invertor_max_kw": config.INVERTOR_MAX_KW,
        "mkd_per_eur": config.MKD_PER_EUR,
        "tarifi": {
            "vt_blokovi": [[g if g else None, c] for g, c in config.VT_BLOKOVI],
            "nt": config.NT_CENA,
            "mrezarina": config.MREZARINA,
            "feed_in": config.FEED_IN,
            "vt_udel": config.VT_UDEL,
            "biznis_cena": config.BIZNIS_CENA,
            "biznis_mrezarina": config.BIZNIS_MREZARINA,
        },
    })


@app.route("/api/sizing", methods=["POST"])
def sizing():
    """ГЛАВНАТА ПРЕСМЕТКА — прима параметри, враќа препорака.

    Влез (JSON):
      greenje:  "struja" | "toplinska" | "drva"
      smetki:   {"mart": 5000, "juni": 3000, "septemvri": 3500, "dekemvri": 9000}
                (може и само една — останатите празни)
      load:     годишна kWh (се користи АКО нема сметки)
      pv:       kWp на соларниот систем

    Излез (JSON): за секоја батерија — заштеда, отплата, NPV + препорака
    """
    p = request.get_json(force=True) or {}
    greenje = p.get("greenje", "struja")
    smetki = p.get("smetki") or {}
    pv_kwp = float(p.get("pv", 5.0))

    # РЕЖИМ: домаќинство (ВТ/НТ тарифи + блокови) или фирма (рамна тарифа)
    rezim = "biznis" if p.get("mode") == "business" else "domakinstvo"

    # --- Од 4-те сметки → kWh + сезонски тежини + маргинален блок ---
    ima_smetki = any(v for v in smetki.values() if v)

    if rezim == "biznis":
        # Фирма: рамна тарифа → проста инверзија (нема блокови)
        cena_po_kwh = config.BIZNIS_CENA + config.BIZNIS_MREZARINA
        if ima_smetki:
            mesecni = [float(v) / cena_po_kwh for v in smetki.values() if v]
            prosek = sum(mesecni) / len(mesecni)
            godisen_kwh = prosek * 12
            tezini = None
        else:
            godisen_kwh = float(p.get("load", 50000))
            tezini = None
        blok, vt_cena = 0, config.BIZNIS_CENA
    elif ima_smetki:
        godisen_kwh, tezini, blok, vt_cena = od_4_smetki(smetki)
    else:
        godisen_kwh = float(p.get("load", 10000))
        tezini = None
        blok, vt_cena = marginalen_blok(godisen_kwh / 12 * 0.5)

    # Manual override на ВТ од формата — само ако НЕМА сметки
    # (кога има сметки, автоматскиот блок е поточен од рачната вредност)
    if p.get("tariff_high") and not ima_smetki:
        vt_cena = float(p["tariff_high"])

    # Кои капацитети да се тестираат (frontend праќа листа; 0 = без батерија)
    katalog = config.BATERII_BIZNIS if rezim == "biznis" else config.BATERII
    caps = [c for c in (p.get("caps") or list(katalog.keys())) if c and c > 0]

    log.info("Барање [%s]: %s kWh/год · %s · %s kWp · цена %.4f",
             rezim, round(godisen_kwh), greenje, pv_kwp, vt_cena)

    # --- Пушти ги LP пресметките за сите батерии ---
    df = PODATOCI[greenje]
    rezultati = testiraj_site_baterii(df, godisen_kwh, pv_kwp, vt_cena,
                                       tezini, caps, rezim)
    najdobra = preporaka(rezultati)

    # --------------------------------------------------------------------------
    # Одговорот е во ИСТИОТ формат како стариот проект — за да работи
    # постоечкиот index.html без промени во render логиката.
    # --------------------------------------------------------------------------
    rows = [{
        "capacity_kwh": float(r["kapacitet_kwh"]),
        "annual_savings_mkd": float(r["zasteda_godisno"]),
        "annual_cost_no_battery_mkd": float(r["trosok_bez"]),
        "annual_cost_with_battery_mkd": float(r["trosok_so"]),
        "investment_mkd": float(r["cena_mkd"]),
        "payback_years": r["otplata_godini"],
        "npv_10yr_mkd": float(r["npv_mkd"]),
        "self_consumption_pct": float(r["self_pct"]),
    } for r in rezultati]

    validni = [r for r in rows if r["capacity_kwh"] > 0]
    so_otplata = [r for r in validni if r["payback_years"] is not None]
    naj_npv = max(validni, key=lambda r: r["npv_10yr_mkd"])
    naj_zasteda = max(validni, key=lambda r: r["annual_savings_mkd"])
    naj_self = max(validni, key=lambda r: r["self_consumption_pct"])
    recommendations = {
        "fastest_payback_kwh": min(so_otplata, key=lambda r: r["payback_years"])["capacity_kwh"] if so_otplata else None,
        "fastest_payback_years": min(so_otplata, key=lambda r: r["payback_years"])["payback_years"] if so_otplata else None,
        "max_savings_kwh": naj_zasteda["capacity_kwh"],
        "max_savings_mkd": naj_zasteda["annual_savings_mkd"],
        "max_npv_kwh": naj_npv["capacity_kwh"],
        "max_npv_mkd": naj_npv["npv_10yr_mkd"],
        "max_self_consumption_kwh": naj_self["capacity_kwh"],
        "max_self_consumption_pct": naj_self["self_consumption_pct"],
    }

    return jsonify({
        "inputs": {
            "load": round(godisen_kwh), "pv": pv_kwp,
            "price": 18941,   # просечна цена/kWh (frontend прави override)
            "tariff_high": vt_cena,
            "tariff_low": config.BIZNIS_CENA if rezim == "biznis" else config.NT_CENA,
            "feed_in": config.FEED_IN, "caps": [0] + caps,
            "greenje": greenje, "blok": blok, "rezim": rezim,
        },
        "rows": rows,
        "recommendations": recommendations,
        "preporaka": najdobra,
    })


def _port_zafaten(port: int) -> bool:
    import socket
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


if __name__ == "__main__":
    PORT = 5002
    if _port_zafaten(PORT):
        print(f"⚠️  Port {PORT} е зафатен. Ослободи го со:  lsof -ti:{PORT} | xargs kill -9")
        raise SystemExit(1)
    log.info("Стартувам на http://127.0.0.1:%d", PORT)
    app.run(host="127.0.0.1", port=PORT, debug=True, use_reloader=False)
