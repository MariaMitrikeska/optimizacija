"""
================================================================================
 LP_OPTIMIZACIJA.PY — Чекор 3: ШТО ДА СЕ ПРАВИ ТОГАШ? (Линеарно Програмирање)
================================================================================

 УЛОГАТА НА ОВОЈ ФАЈЛ ВО ГОЛЕМАТА СЛИКА:
 ----------------------------------------
 ML (ml_prognoza.py) ни кажа ШТО ЌЕ СЕ СЛУЧИ утре:
     „во 12ч сонцето дава 4.2 kW, во 19ч куќата троши 1.5 kWh..."

 Овој фајл одговара на следното прашање: ПА ШТО ДА ПРАВИМЕ ТОГАШ?
     „кога батеријата да се полни? кога да се празни? кога да купиме
      од EVN, кога да продадеме вишок?"

 ┌─────────────────────────────────────────────────────────────────┐
 │  3. LP ја зема прогнозата како ВЛЕЗ                             │
 │           ↓                                                     │
 │  4. LP пресметува: „најевтиниот распоред за батеријата е:       │
 │     полни во 11-14ч (сонце+ефтина тарифа), празни во 18-21ч     │
 │     (вечерен пик+скапа тарифа)"                                 │
 │           ↓                                                     │
 │  5. Батеријата го следи планот → МИНИМАЛНА СМЕТКА               │
 └─────────────────────────────────────────────────────────────────┘

 ШТО Е ЛИНЕАРНО ПРОГРАМИРАЊЕ (LP)?
 ----------------------------------
 Математички метод кој ГАРАНТИРАНО го наоѓа најдоброто решение, кога:
   - имаш ЦЕЛ (минимизирај ја сметката)
   - имаш ОДЛУКИ (за секој час: колку полни/празни/купи/продај)
   - имаш ОГРАНИЧУВАЊА (батеријата има капацитет, физика важи...)
 „Линеарно" = сите правила се прости множења и собирања (2 kWh чини
 двојно од 1 kWh). Тогаш постои брз алгоритам со ДОКАЖАН оптимум.

 Разлика од „прости правила": правило „полни дење, празни навечер" е ОК,
 но LP е ДОКАЖАНО најдобро — ниту еден друг план не дава помала сметка.

 АЛАТКИ: PuLP (Python библиотека за пишување LP) + CBC (бесплатен solver
 што ја решава математиката). Ние ги пишуваме правилата, CBC решава.
================================================================================
"""
from __future__ import annotations

import pandas as pd

import config


def optimalen_dispech(
    load: pd.Series,
    pv: pd.Series,
    cena_uvoz: pd.Series,
    cena_izvoz: float,
    kapacitet_kwh: float,
) -> dict:
    """Најди го НАЈЕВТИНИОТ можен план за батеријата за дадениот период.

    Враќа: {"trosok": вкупна сметка во МКД, "izvoz": продадено kWh, ...}
    """
    import pulp

    T = len(load)

    max_soc = kapacitet_kwh
    min_soc = kapacitet_kwh * config.BATERIJA_MIN_SOC
    max_moknost = max(2.0, kapacitet_kwh * config.BATERIJA_C_RATE)
    eff = config.BATERIJA_EFIKASNOST ** 0.5

    prob = pulp.LpProblem("bateriski_dispech", pulp.LpMinimize)

    kupi = pulp.LpVariable.dicts("kupi", range(T), lowBound=0)
    prodaj = pulp.LpVariable.dicts("prodaj", range(T), lowBound=0)
    polni = pulp.LpVariable.dicts("polni", range(T), lowBound=0, upBound=max_moknost)
    prazni = pulp.LpVariable.dicts("prazni", range(T), lowBound=0, upBound=max_moknost)
    soc = pulp.LpVariable.dicts("soc", range(T + 1), lowBound=min_soc, upBound=max_soc)

    prob += pulp.lpSum(
        kupi[t] * float(cena_uvoz.iloc[t]) - prodaj[t] * cena_izvoz
        for t in range(T)
    )

    prob += soc[0] == kapacitet_kwh * 0.5

    for t in range(T):


        prob += (
            float(load.iloc[t])
            == float(pv.iloc[t]) + kupi[t] - prodaj[t] + prazni[t] - polni[t]
        )

        prob += soc[t + 1] == soc[t] + polni[t] * eff - prazni[t] / eff


        if not config.DOZVOLI_POLNENJE_OD_MREZA:
            visok_sonce = max(0.0, float(pv.iloc[t]) - float(load.iloc[t]))
            prob += polni[t] <= visok_sonce

    prob += soc[T] == kapacitet_kwh * 0.5

    prob.solve(pulp.PULP_CBC_CMD(msg=0))

    status = pulp.LpStatus[prob.status]
    if status != "Optimal":
        raise RuntimeError(
            f"LP не најде оптимално решение (статус: {status}). "
            f"Провери ги влезните податоци — капацитет={kapacitet_kwh} kWh."
        )

    vkupno_prodadeno = sum(prodaj[t].value() or 0.0 for t in range(T))
    return {
        "trosok": float(pulp.value(prob.objective)),
        "izvoz_kwh": float(vkupno_prodadeno),
    }


def bez_baterija(load, pv, cena_uvoz, cena_izvoz) -> dict:
    """Референца: колку чини БЕЗ батерија (за да знаеме колку штеди).

    Без батерија нема одлуки — само аритметика:
      дефицит → купи по цена_увоз · вишок → продај по feed-in
    """
    trosok, izvoz = 0.0, 0.0
    for t in range(len(load)):
        razlika = float(pv.iloc[t]) - float(load.iloc[t])
        if razlika >= 0:
            trosok -= razlika * cena_izvoz
            izvoz += razlika
        else:
            trosok += -razlika * float(cena_uvoz.iloc[t])
    return {"trosok": trosok, "izvoz_kwh": izvoz}

