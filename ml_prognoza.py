"""
================================================================================
 ML_PROGNOZA.PY — Чекор 2: ШТО ЌЕ СЕ СЛУЧИ УТРЕ? (машинско учење)
================================================================================

 УЛОГАТА ВО ГОЛЕМАТА СЛИКА:
 ---------------------------
 Батеријата мора да планира ОДНАПРЕД. За да планира, мора да знае:
   „Колку сонце ќе има утре?"  → тоа го предвидува овој модул.

 ┌─────────────────────────────────────────────────────────────────┐
 │  1. XGBoost ГЛЕДА: час, сезона, температура, облачност,         │
 │                     вчерашна продукција                          │
 │           ↓                                                      │
 │  2. XGBoost КАЖУВА: „утре во 12ч панелите ќе дадат 4.2 kW"      │
 │           ↓                                                      │
 │  3. Прогнозата оди во LP (lp_optimizacija.py) која ОДЛУЧУВА     │
 └─────────────────────────────────────────────────────────────────┘

 ML = ГАТАЧОТ (само предвидува, не одлучува)
 LP = ПЛАНЕРОТ (само одлучува, не предвидува)

 ⚠ Оваа датотека е СИНХРОНИЗИРАНА со ml_prognoza.ipynb — исти features,
   исти хиперпараметри, иста поделба. Notebook-от е за објаснување,
   овој модул за употреба во апликацијата.
================================================================================
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import config

MODEL_PATH = config.DATA / "xgb_model.joblib"

SPLIT_DATUM = "2023-07-01"


def napravi_features(df: pd.DataFrame) -> pd.DataFrame:
    """Од суровите податоци направи ги 22-те влезни колони за моделот."""
    f = df.copy()
    lok = f.index.tz_convert(config.TIMEZONE)

    f["hour_sin"] = np.sin(2 * np.pi * lok.hour / 24)
    f["hour_cos"] = np.cos(2 * np.pi * lok.hour / 24)
    f["doy_sin"] = np.sin(2 * np.pi * lok.dayofyear / 365)
    f["doy_cos"] = np.cos(2 * np.pi * lok.dayofyear / 365)

    if "cloud_cover" in f.columns:
        f["cloud_kvadrat"] = f["cloud_cover"] ** 2 / 100
        f["vedro"] = (f["cloud_cover"] < 20).astype(int)
        f["oblacno"] = (f["cloud_cover"] > 70).astype(int)
        f["cloud_pred"] = f["cloud_cover"].shift(1)
        f["cloud_promena"] = f["cloud_cover"].diff()

    if "cloud_low" in f.columns:
        f["cloud_efektivna"] = (
            3.0 * f["cloud_low"] + 1.5 * f.get("cloud_mid", 0) + 0.5 * f.get("cloud_high", 0)
        ) / 5.0

    f["pv_lag24"] = f["pv_power_kw"].shift(24)
    f["pv_lag48"] = f["pv_power_kw"].shift(48)
    f["pv_lag168"] = f["pv_power_kw"].shift(24 * 7)
    f["pv_prosek7d"] = f["pv_power_kw"].shift(24).rolling(24 * 7).mean()
    f["temp_lag24"] = f["temp_air"].shift(24)

    return f.dropna()


FEATURES_OSNOVNI = ["hour_sin", "hour_cos", "doy_sin", "doy_cos",
                    "temp_air", "temp_lag24", "wind_speed",
                    "pv_lag24", "pv_lag48", "pv_lag168", "pv_prosek7d"]

FEATURES_VREME = ["humidity", "cloud_cover", "cloud_kvadrat", "vedro",
                  "oblacno", "cloud_pred", "cloud_promena"]

FEATURES_OBLACI = ["cloud_low", "cloud_mid", "cloud_high", "cloud_efektivna"]


def izberi_features(df: pd.DataFrame) -> list[str]:
    """Врати ги features што ги има табелата (со облаци ако се достапни)."""
    feats = list(FEATURES_OSNOVNI)
    for grupa in (FEATURES_VREME, FEATURES_OBLACI):
        if all(c in df.columns for c in grupa):
            feats += grupa
    return feats


FEATURES = FEATURES_OSNOVNI


def treniraj(df: pd.DataFrame):
    """Тренирај XGBoost и врати (модел, тест-табела).

    Хиперпараметрите се ИСТИ како во ml_prognoza.ipynb.
    """
    from xgboost import XGBRegressor

    f = napravi_features(df)
    feats = izberi_features(f)
    split = pd.Timestamp(SPLIT_DATUM, tz="UTC")
    train = f[f.index < split]
    test = f[f.index >= split]

    model = XGBRegressor(
        n_estimators=600,
        max_depth=10,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        min_child_weight=3,
        reg_lambda=1.0,
        random_state=config.RANDOM_SEED if hasattr(config, "RANDOM_SEED") else 42,
        n_jobs=-1,
    )

    model.fit(train[feats], train["pv_power_kw"])

    model._feats = feats

    import joblib
    joblib.dump({"model": model, "feats": feats}, MODEL_PATH)
    return model, test


def prognoziraj(model, df_novi_casovi: pd.DataFrame) -> pd.Series:
    """За нови часови → прогноза на PV во kW. Ова е влезот за LP!"""
    feats = getattr(model, "_feats", FEATURES)
    pred = model.predict(df_novi_casovi[feats])
    pred = np.clip(pred, 0, None)
    return pd.Series(pred, index=df_novi_casovi.index, name="pv_prognoza")


def vcitaj_model():
    """Вчитај зачуван модел од диск (без ретренирање)."""
    import joblib
    payload = joblib.load(MODEL_PATH)
    model = payload["model"]
    model._feats = payload["feats"]
    return model


def oceni(model, test: pd.DataFrame) -> dict:
    """Спореди ги прогнозите со РЕАЛНОСТА на тест-периодот.

    Baseline = наивна прогноза „утре = исто како вчера".
    Ако моделот не е подобар од неа — не вреди ништо.
    """
    prognoza = prognoziraj(model, test)
    vistina = test["pv_power_kw"]
    naivna = test["pv_lag24"]

    mae_model = float(np.mean(np.abs(vistina - prognoza)))
    mae_naivna = float(np.mean(np.abs(vistina - naivna)))
    rmse = float(np.sqrt(np.mean((vistina - prognoza) ** 2)))
    r2 = 1 - np.sum((vistina - prognoza) ** 2) / np.sum((vistina - vistina.mean()) ** 2)

    return {
        "MAE модел (kW)": round(mae_model, 3),
        "RMSE модел (kW)": round(rmse, 3),
        "R²": round(float(r2), 3),
        "MAE наивна (kW)": round(mae_naivna, 3),
        "подобрување vs наивна": f"{(1 - mae_model / mae_naivna) * 100:.0f}%",
    }


if __name__ == "__main__":
    from podatoci import zemi_gi_site_podatoci

    df = zemi_gi_site_podatoci()
    print("Тренирам XGBoost (600 дрва) на ~30 месеци историја...\n")
    model, test = treniraj(df)

    print("═" * 55)
    print("ОЦЕНКА НА ТЕСТ (6 месеци што моделот НИКОГАШ ги видел)")
    print("═" * 55)
    for k, v in oceni(model, test).items():
        print(f"  {k:<24}: {v}")

    print("\nНајважни features:")
    vaznost = sorted(zip(model._feats, model.feature_importances_), key=lambda x: -x[1])
    for ime, v in vaznost[:5]:
        print(f"  {ime:<16} {'█' * int(v * 50)} {v * 100:.1f}%")

    print(f"\n✓ Моделот е зачуван во {MODEL_PATH}")
