"""Service layer dla profile targets — read + write DDB PROFILE row.

Read mirror logiki advisor_chat `_load_profile_targets` (te same fallback
defaults). Write merguje 4 attrs z istniejącym profilem (zachowuje email,
name, etc.).
"""

from __future__ import annotations

from typing import Any

from shared.dynamo import get_item, put_item

# Te same defaulty co `advisor_chat.service` — żeby chat i UI byli spójne.
# Owner zauważył 2026-05-08 że LLM używa kcal_target=2000 mimo że nigdy
# nie wpisał — to jest właśnie ten fallback.
DEFAULT_KCAL_TARGET = 2000
DEFAULT_PROTEIN_TARGET_G = 130
DEFAULT_FAT_TARGET_G = 70
DEFAULT_CARBS_TARGET_G = 200


class ProfileNotFoundError(Exception):
    """PROFILE row brak w DDB — handler zwraca 404."""


def get_targets(user_id: str) -> tuple[int, int, int, int, bool]:
    """Zwraca tuple (kcal, protein_g, fat_g, carbs_g, is_default).

    `is_default=True` gdy profile brak attrów — wszystkie 4 są fallback.
    `is_default=False` gdy każde z 4 jest ustawione przez ownera (frontend
    pokazuje wartości jako "ustawione" zamiast "fallback").
    """
    profile = get_item(f"USER#{user_id}", "PROFILE")
    if profile is None:
        raise ProfileNotFoundError(user_id)

    kcal = profile.get("kcal_target")
    protein = profile.get("protein_target_g")
    fat = profile.get("fat_target_g")
    carbs = profile.get("carbs_target_g")

    is_default = kcal is None or protein is None or fat is None or carbs is None

    return (
        int(kcal) if kcal is not None else DEFAULT_KCAL_TARGET,
        int(protein) if protein is not None else DEFAULT_PROTEIN_TARGET_G,
        int(fat) if fat is not None else DEFAULT_FAT_TARGET_G,
        int(carbs) if carbs is not None else DEFAULT_CARBS_TARGET_G,
        is_default,
    )


def update_targets(
    user_id: str,
    kcal: int,
    protein_g: int,
    fat_g: int,
    carbs_g: int,
) -> None:
    """Merge 4 target attrs do PROFILE row. Zachowuje email/name/etc.

    Read-modify-write — race window jest mały (single-user UI form, owner
    nie kliknie 2x naraz). Gdy PROFILE brak — raise ProfileNotFoundError
    (login flow tworzy PROFILE, więc brak = anomalia).
    """
    profile = get_item(f"USER#{user_id}", "PROFILE")
    if profile is None:
        raise ProfileNotFoundError(user_id)

    merged: dict[str, Any] = {**profile}
    merged["kcal_target"] = kcal
    merged["protein_target_g"] = protein_g
    merged["fat_target_g"] = fat_g
    merged["carbs_target_g"] = carbs_g
    # PK/SK są w item ale put_item nakłada własne — wyciągamy:
    merged.pop("PK", None)
    merged.pop("SK", None)

    put_item(f"USER#{user_id}", "PROFILE", merged)
