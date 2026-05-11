"""Service layer dla profile targets — read + write DDB PROFILE row + TDEE calc.

Read mirror logiki advisor_chat `_load_profile_targets` (te same fallback
defaults). Write merguje 4 attrs makro + opcjonalnie 5 attrs body_profile
z istniejącym profilem (zachowuje email, name, etc.).

TDEE calc — Mifflin-St Jeor (najczęściej używana formula w klinicznym
kontekście, lepsza accuracy niż Harris-Benedict 1919). Po BMR aplikujemy
activity multiplier (TDEE) i goal modifier (deficit/surplus).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, cast

from handlers.profile_targets.schemas import (
    ACTIVITY_LEVELS,
    GOAL_MODIFIERS,
    BodyProfile,
)
from shared.dynamo import _table, get_item, put_item

# Sprint 11 PR4 — TDEE history cap mirror handlers/tdee_recalc/service.HISTORY_CAP.
# Cross-handler structural contract (per-handler zip per ADR-002, brak shared
# import) — owner zmienia tę liczbę → musi też w drugim miejscu.
TDEE_HISTORY_CAP = 20

# Te same defaulty co `advisor_chat.service` — żeby chat i UI byli spójne.
# Owner zauważył 2026-05-08 że LLM używa kcal_target=2000 mimo że nigdy
# nie wpisał — to jest właśnie ten fallback.
DEFAULT_KCAL_TARGET = 2000
DEFAULT_PROTEIN_TARGET_G = 130
DEFAULT_FAT_TARGET_G = 70
DEFAULT_CARBS_TARGET_G = 200

# Macro split heurystyki dla `suggest_macros`. Konsensus z literatury
# sportowej (ISSN position stand 2017): 1.6-2.2 g/kg protein dla treningu
# siłowego/wytrzymałościowego, 0.8-1 g/kg fat dla zdrowia hormonalnego.
PROTEIN_G_PER_KG = 1.8
FAT_G_PER_KG = 0.9
KCAL_PER_G_PROTEIN = 4
KCAL_PER_G_FAT = 9
KCAL_PER_G_CARBS = 4


class ProfileNotFoundError(Exception):
    """PROFILE row brak w DDB — handler zwraca 404."""


class WeightNotFoundError(Exception):
    """Brak waga w BIOMETRY (last 100 items) — calculate-tdee wymaga waga."""


def get_targets(user_id: str) -> tuple[int, int, int, int, bool, BodyProfile | None]:
    """Zwraca tuple (kcal, protein_g, fat_g, carbs_g, is_default, body_profile).

    `is_default=True` gdy 4 makro pola brak — wszystkie są fallback.
    `body_profile=None` gdy owner nie przeszedł przez wizard TDEE jeszcze.
    """
    profile = get_item(f"USER#{user_id}", "PROFILE")
    if profile is None:
        raise ProfileNotFoundError(user_id)

    kcal = profile.get("kcal_target")
    protein = profile.get("protein_target_g")
    fat = profile.get("fat_target_g")
    carbs = profile.get("carbs_target_g")

    is_default = kcal is None or protein is None or fat is None or carbs is None

    body_profile = _extract_body_profile(profile)

    return (
        int(kcal) if kcal is not None else DEFAULT_KCAL_TARGET,
        int(protein) if protein is not None else DEFAULT_PROTEIN_TARGET_G,
        int(fat) if fat is not None else DEFAULT_FAT_TARGET_G,
        int(carbs) if carbs is not None else DEFAULT_CARBS_TARGET_G,
        is_default,
        body_profile,
    )


def update_targets(
    user_id: str,
    kcal: int,
    protein_g: int,
    fat_g: int,
    carbs_g: int,
    body_profile: BodyProfile | None = None,
) -> None:
    """Merge 4 target attrs (+ optional 5 body_profile attrs) do PROFILE row.

    Sprint 11 PR4 — gdy `body_profile` initial save lub change (5 fields
    diff vs poprzedni), automatycznie:
    - Reset `tdee_baseline = tdee_adaptive = Mifflin × multiplier`
    - Append `tdee_history` z event marker (`initial` / `body_profile_change`),
      cap 20 FIFO
    - Auto-sync `kcal_target` + 3 makro do nowego baseline (override
      user-provided values w request body — body_profile change ma
      priorytet nad manual makro)

    Wymaga waga w BIOMETRY (last 100 items lookup). Brak waga + body_profile
    change → no TDEE init, manual makro preserved (owner doda waga + retry
    save body_profile albo czeka na PR5 button "Przelicz teraz").

    Read-modify-write — race window mały (single-user UI form). Gdy PROFILE
    brak → ProfileNotFoundError (login flow tworzy PROFILE, brak = anomalia).
    """
    profile = get_item(f"USER#{user_id}", "PROFILE")
    if profile is None:
        raise ProfileNotFoundError(user_id)

    merged: dict[str, Any] = {**profile}

    body_profile_initial = False
    body_profile_changed = False
    if body_profile is not None:
        old_profile = _extract_body_profile(profile)
        if old_profile is None:
            body_profile_initial = True
        elif _body_profile_differs(old_profile, body_profile):
            body_profile_changed = True

        merged["height_cm"] = body_profile.height_cm
        merged["age"] = body_profile.age
        merged["sex"] = body_profile.sex
        merged["activity_level"] = body_profile.activity_level
        merged["goal"] = body_profile.goal

    weight_kg: float | None = None
    if (body_profile_initial or body_profile_changed) and body_profile is not None:
        weight_kg = get_latest_weight_kg(user_id)

    if (
        weight_kg is not None
        and body_profile is not None
        and (body_profile_initial or body_profile_changed)
    ):
        bmr = calculate_bmr(weight_kg, body_profile.height_cm, body_profile.age, body_profile.sex)
        new_baseline = int(round(calculate_tdee(bmr, body_profile.activity_level)))
        new_kcal_target = calculate_target_kcal(new_baseline, body_profile.goal)
        new_protein, new_fat, new_carbs = suggest_macros(weight_kg, new_kcal_target)

        # History entry — structural mirror handlers/tdee_recalc/schemas.RecalcHistoryEntry.
        # Cross-handler import zawodzi (per-handler zip per ADR-002), więc plain
        # dict z dokładną shape. Owner add'uje field tam → mirror tu.
        old_baseline_raw = profile.get("tdee_baseline")
        history_entry: dict[str, Any] = {
            "date": date.today().isoformat(),
            "event": "initial" if body_profile_initial else "body_profile_change",
            "before": int(old_baseline_raw) if old_baseline_raw is not None else None,
            "after": new_baseline,
            "kcal_in_avg": None,
            "waga_delta_kg": None,
            "adjustment": None,
            "capped": False,
            "reason": None,
        }
        history = list(profile.get("tdee_history") or [])
        history.append(history_entry)
        if len(history) > TDEE_HISTORY_CAP:
            history = history[-TDEE_HISTORY_CAP:]

        merged["tdee_baseline"] = new_baseline
        merged["tdee_adaptive"] = new_baseline  # restart pętli adaptive
        merged["tdee_last_recalc"] = None
        merged["tdee_history"] = history
        merged["kcal_target"] = new_kcal_target
        merged["protein_target_g"] = new_protein
        merged["fat_target_g"] = new_fat
        merged["carbs_target_g"] = new_carbs
    else:
        # No body_profile change (lub brak waga) → user-provided values preserved.
        merged["kcal_target"] = kcal
        merged["protein_target_g"] = protein_g
        merged["fat_target_g"] = fat_g
        merged["carbs_target_g"] = carbs_g

    merged.pop("PK", None)
    merged.pop("SK", None)
    put_item(f"USER#{user_id}", "PROFILE", merged)


def _body_profile_differs(old: BodyProfile, new: BodyProfile) -> bool:
    """5-field strict diff (Pydantic equality jest też OK, ale explicit jaśniejsze)."""
    return (
        old.height_cm != new.height_cm
        or old.age != new.age
        or old.sex != new.sex
        or old.activity_level != new.activity_level
        or old.goal != new.goal
    )


def _decimal_to_native(value: Any) -> Any:
    """Rekursywna konwersja Decimal → int/float dla JSON serialization.

    DDB zwraca Number jako Decimal; `json.dumps` nie umie. Pydantic
    `dict[str, Any]` field nie konwertuje passthrough. Stosujemy przed
    zwróceniem `tdee_history`/`tdee_last_recalc` z `get_tdee_state`.
    """
    if isinstance(value, Decimal):
        return int(value) if value % 1 == 0 else float(value)
    if isinstance(value, dict):
        return {k: _decimal_to_native(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_decimal_to_native(v) for v in value]
    return value


def get_tdee_state(user_id: str) -> dict[str, Any]:
    """Read-only TDEE state z PROFILE — `tdee_baseline`/`adaptive`/`last_recalc`/`history`.

    Wszystkie pola opcjonalne (None / []) gdy owner jeszcze nie przeszedł
    przez body_profile init (PR4) ani manual recalc (PR2). Handler składa
    z `get_targets()` w pełną `TargetsResponse`.

    Decimal recursive coercion — DDB Number type wraca jako Decimal,
    `json.dumps` w handlerze nie umie. Konwertujemy przed return.
    """
    profile = get_item(f"USER#{user_id}", "PROFILE")
    if profile is None:
        return {
            "tdee_baseline": None,
            "tdee_adaptive": None,
            "tdee_last_recalc": None,
            "tdee_history": [],
        }
    last_recalc = profile.get("tdee_last_recalc")
    return {
        "tdee_baseline": int(profile["tdee_baseline"])
        if profile.get("tdee_baseline") is not None
        else None,
        "tdee_adaptive": int(profile["tdee_adaptive"])
        if profile.get("tdee_adaptive") is not None
        else None,
        "tdee_last_recalc": _decimal_to_native(dict(last_recalc)) if last_recalc else None,
        "tdee_history": _decimal_to_native(list(profile.get("tdee_history") or [])),
    }


def get_latest_weight_kg(user_id: str, *, lookback_items: int = 100) -> float | None:
    """Latest weight value z BIOMETRY rows. Walks SK desc, returns pierwszy weight.

    Implementation: 1 Query z `ScanIndexForward=False` + Limit=100 — chwyta
    ~7-14 dni biometry (13 metryk × ~1-2 entries/dzień). Najnowsza waga
    powinna być w pierwszych ~26 items.
    """
    resp = _table.query(
        KeyConditionExpression="PK = :pk AND begins_with(SK, :skp)",
        ExpressionAttributeValues={":pk": f"USER#{user_id}", ":skp": "BIOMETRY#"},
        ScanIndexForward=False,
        Limit=lookback_items,
    )
    for item in resp.get("Items", []):
        sk = cast(str, item["SK"])
        # Format: BIOMETRY#YYYY-MM-DD#metric[#ts]
        parts = sk.split("#")
        if len(parts) >= 3 and parts[2] == "weight":
            kg = item.get("kg")
            if kg is not None:
                # DDB attr type to Decimal/Number — float() narrowing przez str().
                return float(str(kg))
    return None


def calculate_bmr(weight_kg: float, height_cm: int, age: int, sex: str) -> float:
    """Mifflin-St Jeor formula (J Am Diet Assoc 1990).

    Najczęściej używana w klinicznym kontekście — ~10% lepsza accuracy
    niż Harris-Benedict 1919 dla większości populacji.

        BMR = 10 × kg + 6.25 × cm − 5 × age + s
        s = +5 dla mężczyzn, −161 dla kobiet
    """
    base = 10.0 * weight_kg + 6.25 * height_cm - 5.0 * age
    sex_offset = 5 if sex == "male" else -161
    return base + sex_offset


def calculate_tdee(bmr: float, activity_level: str) -> float:
    """TDEE = BMR × activity multiplier (poza strukturyzowanymi treningami).

    Strava activities (kcal_active) i HAE active_energy są dorzucane osobno
    przez advisor — multiplier pokrywa baseline NEAT/movement.
    """
    return bmr * ACTIVITY_LEVELS[activity_level]


def calculate_target_kcal(tdee: float, goal: str) -> int:
    """TDEE + goal modifier. Round do najbliższej 10 kcal (UX precision)."""
    raw = tdee + GOAL_MODIFIERS[goal]
    return int(round(raw / 10) * 10)


def suggest_macros(weight_kg: float, target_kcal: int) -> tuple[int, int, int]:
    """Zwraca (protein_g, fat_g, carbs_g) z heurystyki:
    - protein 1.8 g/kg (4 kcal/g)
    - fat 0.9 g/kg (9 kcal/g)
    - carbs = pozostałe kcal / 4

    Round do najbliższej 5 g (precision UX form). Carbs floor 30g
    (dolny limit Pydantic w TargetsPayload — ketogenic edge case).
    """
    protein_g = round(weight_kg * PROTEIN_G_PER_KG / 5) * 5
    fat_g = round(weight_kg * FAT_G_PER_KG / 5) * 5
    used_kcal = protein_g * KCAL_PER_G_PROTEIN + fat_g * KCAL_PER_G_FAT
    carbs_kcal = max(target_kcal - used_kcal, 30 * KCAL_PER_G_CARBS)
    carbs_g = round(carbs_kcal / KCAL_PER_G_CARBS / 5) * 5
    return int(protein_g), int(fat_g), int(carbs_g)


def _extract_body_profile(profile: dict[str, Any]) -> BodyProfile | None:
    """Z DDB row attrs zbuduj BodyProfile jeśli wszystkie 5 pól obecne."""
    required = ("height_cm", "age", "sex", "activity_level", "goal")
    if not all(profile.get(field) is not None for field in required):
        return None
    return BodyProfile(
        height_cm=int(profile["height_cm"]),
        age=int(profile["age"]),
        sex=cast(Any, profile["sex"]),
        activity_level=cast(Any, profile["activity_level"]),
        goal=cast(Any, profile["goal"]),
    )
