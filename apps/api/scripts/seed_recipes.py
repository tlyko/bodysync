"""Seed script — parse 5 PDFów Lidla/Biedronki w `samples/recipes/`, embed
przez OpenAI `text-embedding-3-small`, build FAISS index, upload do S3 +
DDB BatchWrite (Sprint 6.2 PR2 Step 2 per ADR-007).

Local-only, jednorazowy. Wymaga:
- AWS creds (boto3 default chain) z dostępem do bodysync-data-{account}
  bucket + bodysync-data DDB table.
- SSM `/bodysync/openai/api_key` wpisany przez ownera (real OpenAI key).

Idempotent — re-run nadpisuje DDB items (PutItem) i S3 obiekty.

Run:
    cd apps/api
    pip install -e .[seed]
    python scripts/seed_recipes.py --pdf-dir ../../samples/recipes/ --dry-run
    # po dry-run preview, real:
    python scripts/seed_recipes.py --pdf-dir ../../samples/recipes/

Decyzje implementacyjne (per spec adjusts vs ADR-007 D5):

1. **Drop Anthropic Vision fallback.** Wszystkie 5 PDFów są text-native;
   pdfplumber zwraca clean Polish text. Strony bez przepisu (cover, ToC,
   intro) wypadają naturalnie przez missing required fields (kcal,
   Składniki). YAGNI — nie palimy $0.05 na Vision skoro nie potrzeba.

2. **Wersje kobiet/mężczyzn → osobne rekordy.** Każdy split ma INNE
   makro (np. owsianka 473 vs 680 kcal), więc embedding text też się
   różni (kcal w embedding tekscie). Slug dostaje sufix `-mezczyzni`
   żeby SK był unikalny. Haiku w retrieval phase widzi obie wersje
   i wybiera odpowiednią.

3. **Dwa formaty PDF.** "najszybsze-*" (Lidl/Biedronka — 4 PDFy,
   ingredient line `{name} {qty} {unit}`) vs "szybkie-obiady-*"
   (Agata Porębska — 1 PDF, ingredient line ODWROTNY:
   `{qty} {unit} ({serving}) {name}`, headers UPPERCASE). Detect format
   po obecności `Czas przygotowania` (Lidl) vs `CZAS PRZYGOTOWANIA`
   (Porębska) w pierwszych 5 liniach.

4. **Dry-run includes embedding call.** Embedding 200 recipes ~= $0.001,
   nie ma sensu skip'ować — preview embedding text quality jest cenna
   informacja przed real run. Skip'owane są TYLKO writes do S3/DDB.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import boto3
import pdfplumber
from pydantic import BaseModel, Field
from unidecode import unidecode

# `shared.logging` jest absolute-importable jeśli script uruchamiany z
# katalogu `apps/api/` (PYTHONPATH=. lub `python -m scripts.seed_recipes`).
# Tu używamy prostego basicConfig — script-only, JSON logger Lambda overkill.
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("seed_recipes")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OPENAI_SSM_KEY = "/bodysync/openai/api_key"
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIM = 1536
DEFAULT_TABLE = "bodysync-data"
DEFAULT_REGION = "eu-west-1"

# meal_type from filename slug. Note: `desery-i-przekaski` → `przekaska`
# (per ADR-007 standard meal types: sniadanie/obiad/kolacja/przekaska).
MEAL_TYPE_BY_FILENAME: dict[str, str] = {
    "sniadania": "sniadanie",
    "obiady": "obiad",
    "kolacje": "kolacja",
    "desery-i-przekaski": "przekaska",
    "obiady-dla-zapracowanych": "obiad",
}

MealType = Literal["sniadanie", "obiad", "kolacja", "przekaska"]
GenderVariant = Literal["kobiety", "mezczyzni", "neutral"]

# Macros line: `473 kcal 20,9 g 73,4 g 10,6 g 2,8 g 10,2 g 122 mg`
# (kcal, białko, węglowodany, tłuszcze, nasycone, błonnik, sód).
# Polish decimal: comma. PDF czasem wstawia spacje przy wartościach `< 1`.
MACROS_RE = re.compile(
    r"(?P<kcal>\d{2,4})\s*kcal\s+"
    r"(?P<protein>\d+(?:[.,]\d+)?)\s*g\s+"
    r"(?P<carbs>\d+(?:[.,]\d+)?)\s*g\s+"
    r"(?P<fat>\d+(?:[.,]\d+)?)\s*g\s+"
    r"(?P<sat_fat>\d+(?:[.,]\d+)?)\s*g\s+"
    r"(?P<fiber>\d+(?:[.,]\d+)?)\s*g\s+"
    r"(?P<sodium>\d+(?:[.,]\d+)?)\s*mg",
    re.IGNORECASE,
)

# Ingredient line — Lidl format: `Mleko 200 ml (3/4 x szklanka)`.
# Unit może być `g`, `ml`, `szt`, `łyżka`, `łyżeczka`, `garść`, `kostka`,
# `opakowanie`, `ząbek`, `szczypta`. Quantity w pierwszych dwóch grupach
# ma być przed unitem; opis serving (3/4 x szklanka) opcjonalny.
INGREDIENT_RE_LIDL = re.compile(
    r"^(?P<name>[A-ZŻŹĆĄŚĘŁŃÓa-zżźćąśęłńó][^\d]+?)\s+"
    r"(?P<qty>\d+(?:[.,]\d+)?)\s*"
    r"(?P<unit>g|ml|szt\w*|łyżk\w*|łyżeczk\w*|garść|kostka|opakowanie|ząbek|szczypta)\b"
    r"(?:\s*\((?P<serving>[^)]+)\))?\s*$"
)

# Porębska ("szybkie-obiady-*") format: `150 g (1/4 x opakowanie) Gnocchi
# ziemniaczane`. Quantity FIRST, name LAST. Note: szczypta lines are like
# `1 g (1 x szczypta) Pieprz czarny`.
INGREDIENT_RE_POREB = re.compile(
    r"^(?P<qty>\d+(?:[.,]\d+)?)\s*"
    r"(?P<unit>g|ml|szt\w*|łyżk\w*|łyżeczk\w*|garść|kostka|opakowanie|ząbek|szczypta)\b"
    r"(?:\s*\((?P<serving>[^)]+)\))?\s+"
    r"(?P<name>[A-ZŻŹĆĄŚĘŁŃÓa-zżźćąśęłńó].+)$"
)

# Linia z numerowanym krokiem instrukcji: `1. Jabłko zetrzeć...`.
INSTRUCTION_STEP_RE = re.compile(r"^(?P<idx>\d+)\.\s+(?P<text>.+)$")

# Czas przygotowania value (np. `10 minut`, `15minut`, `1h 30min`).
PREP_RE = re.compile(
    r"Czas przygotowania\s*\n+\s*(\d+)\s*minut",
    re.IGNORECASE,
)
PREP_RE_POREB = re.compile(r"^(\d+)\s*MINUT\b", re.IGNORECASE | re.MULTILINE)

DIFFICULTY_RE = re.compile(r"(Łatwy|Średni|Trudny)", re.IGNORECASE)
SERVINGS_RE_LIDL = re.compile(
    r"Liczba porcji\s*\n+\s*(\d+(?:[.,]\d+)?)",
    re.IGNORECASE,
)

# Tag candidates (CAPS lines bez numeru/cyfry; eliminujemy mikronutrienty
# typu `Magnez 29%` po fakcie filterem).
TAG_KEYWORDS: set[str] = {
    "WEGETARIAŃSKIE",
    "WEGAŃSKIE",
    "BOGATE W BŁONNIK",
    "BOGATE",
    "WYSOKA ZAWARTOŚĆ BIAŁKA",
    "ŹRÓDŁO KWASÓW OMEGA-3",
    "GOTOWIEC W UŻYCIU",
    "IDEALNE NA WYNOS",
    "ZAWIERA SOJĘ",
    "ZAWIERA GLUTEN",
    "BEZGLUTENOWE",
    "BEZ LAKTOZY",
}


# ---------------------------------------------------------------------------
# Domain model
# ---------------------------------------------------------------------------


class RecipeData(BaseModel):
    """Parsed recipe row, pre-DDB. `embedding_text` populated separately."""

    slug: str
    name: str
    meal_type: MealType
    kcal: int
    protein_g: float
    fat_g: float
    carbs_g: float
    fiber_g: float | None = None
    sodium_mg: float | None = None
    prep_minutes: int
    difficulty: str
    servings: float = 1.0
    gender_variant: GenderVariant = "neutral"
    ingredients: list[dict[str, Any]] = Field(default_factory=list)
    instructions: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    source_pdf: str
    source_page: int  # 1-indexed
    embedding_text: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _polish_float(raw: str) -> float:
    """Polish decimal `1,5` → 1.5."""
    return float(raw.replace(",", "."))


def slugify(name: str) -> str:
    """unidecode + lowercase + kebab-case + truncate 80 chars (DDB SK budget)."""
    ascii_form = unidecode(name).lower()
    kebab = re.sub(r"[^a-z0-9]+", "-", ascii_form).strip("-")
    return kebab[:80].rstrip("-")


def detect_meal_type(pdf_path: Path) -> MealType:
    """Map filename slug → meal_type. Raises on unknown filename."""
    name = pdf_path.stem.lower()
    for slug_token, meal in MEAL_TYPE_BY_FILENAME.items():
        if slug_token in name:
            return meal  # type: ignore[return-value]
    raise ValueError(f"Cannot infer meal_type from filename: {pdf_path.name}")


def detect_format(text: str) -> Literal["lidl", "poreb"]:
    """Lidl ('Czas przygotowania' lowercase) vs Porębska ('CZAS PRZYGOTOWANIA' uppercase)."""
    if "CZAS PRZYGOTOWANIA" in text:
        return "poreb"
    return "lidl"


def detect_gender_variant(text: str) -> GenderVariant:
    """Lidl PDFy mają na górze 'Wersja dla kobiet'/'Wersja dla mężczyzn'."""
    head = text[:200].lower()
    if "wersja dla kobiet" in head:
        return "kobiety"
    if "wersja dla mężczyzn" in head:
        return "mezczyzni"
    # Porębska — split kobiety/mężczyźni jest w SPIS POSIŁKÓW level (osobne
    # sekcje stron), nie per-page header. Zostawiamy `neutral`; Haiku
    # rozróżnia po kontekście.
    return "neutral"


# ---------------------------------------------------------------------------
# Page parsing
# ---------------------------------------------------------------------------


def _extract_name_lidl(lines: list[str]) -> str | None:
    """Lidl: 1-2 linie nazwy między 'Wersja dla X' a 'Czas przygotowania'."""
    name_parts: list[str] = []
    started = False
    for line in lines:
        stripped = line.strip()
        if not started:
            if stripped.lower().startswith("wersja dla"):
                started = True
            continue
        if stripped.lower().startswith("czas przygotowania"):
            break
        if stripped:
            name_parts.append(stripped)
        if len(name_parts) >= 3:  # safety: max 3 lines for a name
            break
    if not name_parts:
        # No "Wersja dla X" header (some pages skip it). Fallback: first
        # non-empty line if it doesn't look like nav junk.
        for stripped in (line.strip() for line in lines):
            if stripped and not stripped.lower().startswith("czas przygotowania"):
                return stripped
            if stripped.lower().startswith("czas przygotowania"):
                return None
    return " ".join(name_parts) or None


def _extract_name_poreb(lines: list[str]) -> str | None:
    """Porębska: trzecia linia (po `10 MINUT...` + `CZAS PRZYGOTOWANIA...`),
    typowo UPPERCASE."""
    for i, line in enumerate(lines):
        if line.strip().upper().startswith("CZAS PRZYGOTOWANIA"):
            if i + 1 < len(lines):
                candidate = lines[i + 1].strip()
                if candidate and candidate == candidate.upper() and len(candidate) > 3:
                    # Title case for storage; embedding text uses original.
                    return candidate.title()
            break
    return None


def _extract_ingredients(text: str, fmt: Literal["lidl", "poreb"]) -> list[dict[str, Any]]:
    """Parse składniki z całego tekstu strony.

    Lidl: linie typu `Jabłko 180 g (sztuka)` w sekcji między `Składniki`
    a `Wartości odżywcze`. pdfplumber miesza linie składników z liniami
    przygotowania (układ dwukolumnowy), więc filtrujemy regex'em — linie
    NIE pasujące do INGREDIENT_RE_LIDL są skip'owane.

    Porębska: ten sam pattern z odwróconym INGREDIENT_RE_POREB; sekcja
    między `SKŁADNIKI` a `WSKAZÓWKI`/`kcal`.
    """
    if fmt == "lidl":
        section_re = re.compile(
            r"Składniki(.+?)(?:Wartości odżywcze|\d+\s*kcal\s)",
            re.DOTALL | re.IGNORECASE,
        )
        ingredient_re = INGREDIENT_RE_LIDL
    else:
        section_re = re.compile(
            r"SKŁADNIKI(.+?)(?:WSKAZÓWKI|\d+\s*kcal\s)",
            re.DOTALL,
        )
        ingredient_re = INGREDIENT_RE_POREB

    m = section_re.search(text)
    if not m:
        return []
    section = m.group(1)
    out: list[dict[str, Any]] = []
    for raw_line in section.split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        match = ingredient_re.match(line)
        if not match:
            continue
        try:
            qty = _polish_float(match.group("qty"))
        except ValueError:
            continue
        out.append(
            {
                "name": match.group("name").strip(),
                "quantity": qty,
                "unit": match.group("unit").lower(),
                "serving": (match.group("serving") or "").strip() or None,
                "raw": line,
            }
        )
    return out


def _extract_instructions(text: str) -> list[str]:
    """Parse linie zaczynające się od `1.`, `2.`, ... — robust na obie formaty.

    pdfplumber wkleja kroki w środek listy składników (dwukolumnowy
    layout). Iterujemy CAŁY tekst strony, zbieramy linie pasujące do
    INSTRUCTION_STEP_RE, sortujemy po `idx` i zwracamy `text` part.

    Multi-line steps (krok przekraczający szerokość kolumny) są klejone:
    jeśli kolejna linia NIE zaczyna się od cyfry-z-kropką, doklejamy ją
    do ostatniego kroku.
    """
    steps: dict[int, list[str]] = {}
    last_idx: int | None = None
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            last_idx = None
            continue
        m = INSTRUCTION_STEP_RE.match(line)
        if m:
            idx = int(m.group("idx"))
            # Cap idx 1-30 — większe to numerki stron lub artefakty.
            if 1 <= idx <= 30:
                steps[idx] = [m.group("text").strip()]
                last_idx = idx
            else:
                last_idx = None
        else:
            # Continuation of previous step? Tylko jeśli linia jest "treścią"
            # (nie hasło, nie macros, nie nazwa składnika).
            if last_idx is not None and line and not line[0].isdigit():
                # Skip lines with macros (`473 kcal ...`) or składnik patterns.
                if "kcal" in line.lower() or INGREDIENT_RE_LIDL.match(line):
                    last_idx = None
                    continue
                steps[last_idx].append(line)
    return [" ".join(steps[i]) for i in sorted(steps.keys())]


def _extract_tags(text: str) -> list[str]:
    """Wyciąga znane tagi z TAG_KEYWORDS (multi-line CAPS phrases)."""
    found: list[str] = []
    upper = text.upper()
    for kw in TAG_KEYWORDS:
        # Multi-line tags ('BOGATE\nW BŁONNIK') — match z \s+ wildcard.
        pattern = re.compile(r"\b" + r"\s+".join(re.escape(p) for p in kw.split()) + r"\b")
        if pattern.search(upper):
            found.append(kw)
    return found


def parse_page(
    page: pdfplumber.page.Page,
    page_num: int,
    pdf_name: str,
    meal_type: MealType,
    section_variant: GenderVariant = "neutral",
) -> RecipeData | None:
    """Parse one PDF page → RecipeData lub None jeśli nie jest stroną przepisu.

    Skip rules (return None):
    - empty/sparse text (< 50 chars)
    - missing required keywords ('kcal' i 'kładniki')
    - macros line nieparsowalny
    - missing recipe name
    """
    text = page.extract_text() or ""
    if len(text) < 50:
        logger.debug("page=%d short_text=%d skip", page_num, len(text))
        return None

    if "kcal" not in text.lower() or ("kładniki" not in text and "KŁADNIKI" not in text):
        return None

    fmt = detect_format(text)
    lines = text.split("\n")

    name = _extract_name_lidl(lines) if fmt == "lidl" else _extract_name_poreb(lines)
    if not name:
        logger.warning("page=%d pdf=%s missing_name skip", page_num, pdf_name)
        return None

    macros_match = MACROS_RE.search(text)
    if not macros_match:
        logger.warning(
            "page=%d pdf=%s name=%r missing_macros skip",
            page_num,
            pdf_name,
            name[:40],
        )
        return None

    # Prep minutes — Lidl ma na 2 liniach, Porębska na pierwszej linii.
    prep_match = PREP_RE.search(text)
    if not prep_match:
        prep_match = PREP_RE_POREB.search(text)
    if not prep_match:
        logger.warning("page=%d name=%r missing_prep skip", page_num, name[:40])
        return None
    prep_minutes = int(prep_match.group(1))

    # Difficulty — szukamy w tekście (case insensitive).
    diff_match = DIFFICULTY_RE.search(text)
    difficulty = diff_match.group(1).title() if diff_match else "Łatwy"

    # Servings — Lidl: regex multi-line; Porębska: pierwsza linia
    # `10 MINUT 1 ŁATWY` → servings = 1.
    servings = 1.0
    if fmt == "lidl":
        sv_match = SERVINGS_RE_LIDL.search(text)
        if sv_match:
            servings = _polish_float(sv_match.group(1))
    else:
        # `10 MINUT 1 ŁATWY` — drugi token to liczba porcji.
        head_match = re.match(
            r"^\d+\s*MINUT\s+(\d+(?:[.,]\d+)?)\s+(?:ŁATWY|ŚREDNI|TRUDNY)",
            lines[0] if lines else "",
            re.IGNORECASE,
        )
        if head_match:
            servings = _polish_float(head_match.group(1))

    ingredients = _extract_ingredients(text, fmt)
    instructions = _extract_instructions(text)
    tags = _extract_tags(text)
    # Lidl per-page header > Porębska section-level state.
    page_variant = detect_gender_variant(text)
    gender_variant: GenderVariant = page_variant if page_variant != "neutral" else section_variant

    if not ingredients:
        logger.warning(
            "page=%d name=%r no_ingredients_parsed skip",
            page_num,
            name[:40],
        )
        return None
    if not instructions:
        logger.warning(
            "page=%d name=%r no_instructions_parsed skip",
            page_num,
            name[:40],
        )
        return None

    base_slug = slugify(name)
    if gender_variant != "neutral":
        slug = f"{base_slug}-{gender_variant}"[:80].rstrip("-")
    else:
        slug = base_slug

    return RecipeData(
        slug=slug,
        name=name,
        meal_type=meal_type,
        kcal=int(macros_match.group("kcal")),
        protein_g=_polish_float(macros_match.group("protein")),
        fat_g=_polish_float(macros_match.group("fat")),
        carbs_g=_polish_float(macros_match.group("carbs")),
        fiber_g=_polish_float(macros_match.group("fiber")),
        sodium_mg=_polish_float(macros_match.group("sodium")),
        prep_minutes=prep_minutes,
        difficulty=difficulty,
        servings=servings,
        gender_variant=gender_variant,
        ingredients=ingredients,
        instructions=instructions,
        tags=tags,
        source_pdf=pdf_name,
        source_page=page_num,
    )


def parse_all_pdfs(pdf_dir: Path, limit: int | None = None) -> list[RecipeData]:
    """Iterate przez wszystkie *.pdf w katalogu, parse per-page."""
    pdfs = sorted(pdf_dir.glob("*.pdf"))
    if limit is not None:
        pdfs = pdfs[:limit]
    if not pdfs:
        raise FileNotFoundError(f"No *.pdf in {pdf_dir}")
    out: list[RecipeData] = []
    counts: dict[str, int] = {}
    for pdf_path in pdfs:
        meal_type = detect_meal_type(pdf_path)
        per_pdf = 0
        # Section state — Porębska PDF ma `SPIS POSIŁKÓW W WERSJI DLA KOBIET`
        # ~page 6, `... DLA MĘŻCZYZN` ~page 36; każde otwarcie ToC przełącza
        # section_variant. Lidl PDFy używają per-page 'Wersja dla X' headera
        # (page_variant w parse_page), więc section state jest neutral.
        section_variant: GenderVariant = "neutral"
        with pdfplumber.open(pdf_path) as pdf:
            for i, page in enumerate(pdf.pages):
                page_text = page.extract_text() or ""
                if "SPIS POSIŁKÓW" in page_text:
                    upper = page_text.upper()
                    if "DLA KOBIET" in upper:
                        section_variant = "kobiety"
                    elif "DLA MĘŻCZYZN" in upper or "DLA MEZCZYZN" in upper:
                        section_variant = "mezczyzni"
                    continue  # ToC page — never a recipe
                recipe = parse_page(page, i + 1, pdf_path.name, meal_type, section_variant)
                if recipe is not None:
                    out.append(recipe)
                    per_pdf += 1
        counts[pdf_path.name] = per_pdf
        logger.info("parsed pdf=%s recipes=%d", pdf_path.name, per_pdf)
    logger.info("parse_summary total=%d by_pdf=%s", len(out), counts)
    return out


def deduplicate(recipes: list[RecipeData]) -> list[RecipeData]:
    """Drop dupy po slug — keep first."""
    seen: set[str] = set()
    out: list[RecipeData] = []
    dupes = 0
    for r in recipes:
        if r.slug in seen:
            dupes += 1
            continue
        seen.add(r.slug)
        out.append(r)
    if dupes:
        logger.info("deduplicate dropped=%d", dupes)
    return out


# ---------------------------------------------------------------------------
# Embedding + FAISS
# ---------------------------------------------------------------------------


def build_embedding_text(recipe: RecipeData) -> str:
    """Single-line ~150-250 tokens — name + meal + składniki TOP-10 + tagi + makro.

    Per ADR-007 D5: embedding text musi unikalnie identyfikować przepis
    semantycznie (do retrieval po user query "obiad wysokobiałkowy").
    """
    ingredient_names = [i["name"] for i in recipe.ingredients[:10]]
    ingredients_str = ", ".join(ingredient_names)
    tags_str = ", ".join(recipe.tags) if recipe.tags else "brak"
    return (
        f"{recipe.name}. {recipe.meal_type}. "
        f"Składniki: {ingredients_str}. "
        f"Tagi: {tags_str}. "
        f"{recipe.kcal}kcal, {recipe.protein_g}g białka, "
        f"{recipe.fat_g}g tłuszczu, {recipe.carbs_g}g węgli."
    )


def embed_batch(texts: list[str], openai_api_key: str) -> list[list[float]]:
    """Single-batch embed call. 200 recipes mieszczą się w 2048 input limit.

    OpenAI zwraca `data: [{embedding: [...], index: i}, ...]`. Sortujemy
    po `index` żeby odzyskać kolejność input'u (gwarancja niedokumentowana
    explicite, ale empirycznie tak działa — defensive sort).
    """
    from openai import OpenAI

    client = OpenAI(api_key=openai_api_key)
    t0 = time.monotonic()
    response = client.embeddings.create(model=EMBEDDING_MODEL, input=texts)
    elapsed = time.monotonic() - t0
    sorted_data = sorted(response.data, key=lambda d: d.index)
    logger.info(
        "embed_complete count=%d elapsed_s=%.2f tokens=%d",
        len(sorted_data),
        elapsed,
        response.usage.total_tokens,
    )
    return [list(d.embedding) for d in sorted_data]


def build_faiss_index(embeddings: list[list[float]]) -> Any:
    """np.array → L2-normalize → IndexFlatIP (cosine sim via inner product)."""
    import faiss
    import numpy as np

    arr = np.array(embeddings, dtype=np.float32)
    if arr.shape[1] != EMBEDDING_DIM:
        raise ValueError(f"Embedding dim mismatch: got {arr.shape[1]}, want {EMBEDDING_DIM}")
    faiss.normalize_L2(arr)
    index = faiss.IndexFlatIP(EMBEDDING_DIM)
    index.add(arr)
    logger.info("faiss_index_built size=%d dim=%d", index.ntotal, EMBEDDING_DIM)
    return index


# ---------------------------------------------------------------------------
# AWS writes
# ---------------------------------------------------------------------------


def upload_to_s3(index: Any, recipes: list[RecipeData], bucket: str, region: str) -> None:
    """faiss.write_index → S3 + recipes-metadata.json (ordered po faiss_id)."""
    import faiss

    s3 = boto3.client("s3", region_name=region)
    tmp_path = "/tmp/seed-faiss.bin"  # noqa: S108  # script-only
    faiss.write_index(index, tmp_path)
    s3.upload_file(tmp_path, bucket, "recipes/faiss-index.bin")

    metadata = [
        {
            "slug": r.slug,
            "meal_type": r.meal_type,
            "name": r.name,
            "gender_variant": r.gender_variant,
        }
        for r in recipes
    ]
    s3.put_object(
        Bucket=bucket,
        Key="recipes/recipes-metadata.json",
        Body=json.dumps(metadata, ensure_ascii=False).encode("utf-8"),
        ContentType="application/json",
    )
    size_kb = os.path.getsize(tmp_path) / 1024
    logger.info(
        "s3_upload bucket=%s faiss_kb=%.1f metadata_count=%d",
        bucket,
        size_kb,
        len(metadata),
    )


def _to_decimal(value: Any) -> Any:
    """DDB nie przyjmuje float — convert do Decimal rekurencyjnie."""
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, list):
        return [_to_decimal(v) for v in value]
    if isinstance(value, dict):
        return {k: _to_decimal(v) for k, v in value.items()}
    return value


def write_to_ddb(recipes: list[RecipeData], table_name: str, region: str) -> None:
    """BatchWrite (auto-batched 25/req przez batch_writer context).

    PK = 'RECIPES' (constant, NIE per-user — recipe katalog jest globalny).
    SK = 'RECIPE#{meal_type}#{slug}'.
    """
    table = boto3.resource("dynamodb", region_name=region).Table(table_name)
    with table.batch_writer() as batch:
        for r in recipes:
            attrs = r.model_dump()
            item: dict[str, Any] = {
                "PK": "RECIPES",
                "SK": f"RECIPE#{r.meal_type}#{r.slug}",
                **_to_decimal(attrs),
            }
            batch.put_item(Item=item)
    logger.info("ddb_write table=%s items=%d", table_name, len(recipes))


# ---------------------------------------------------------------------------
# OpenAI key + bucket discovery
# ---------------------------------------------------------------------------


def _get_openai_key(region: str) -> str:
    """Read OpenAI API key z SSM SecureString, fail-fast na PLACEHOLDER."""
    ssm = boto3.client("ssm", region_name=region)
    resp = ssm.get_parameter(Name=OPENAI_SSM_KEY, WithDecryption=True)
    value: str = resp["Parameter"]["Value"]
    if value == "PLACEHOLDER" or len(value) < 20:
        raise SystemExit(
            f"SSM {OPENAI_SSM_KEY} = PLACEHOLDER. Wpisz real key w AWS Console przed run'em."
        )
    return value


def _resolve_bucket(arg: str | None, region: str) -> str:
    """`--bucket` flag > env BODYSYNC_DATA_BUCKET > `bodysync-data-{account_id}`."""
    if arg:
        return arg
    env = os.environ.get("BODYSYNC_DATA_BUCKET")
    if env:
        return env
    sts = boto3.client("sts", region_name=region)
    account_id = sts.get_caller_identity()["Account"]
    return f"bodysync-data-{account_id}"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _summarize(recipes: list[RecipeData]) -> dict[str, Any]:
    by_meal: dict[str, int] = {}
    by_pdf: dict[str, int] = {}
    by_variant: dict[str, int] = {}
    for r in recipes:
        by_meal[r.meal_type] = by_meal.get(r.meal_type, 0) + 1
        by_pdf[r.source_pdf] = by_pdf.get(r.source_pdf, 0) + 1
        by_variant[r.gender_variant] = by_variant.get(r.gender_variant, 0) + 1
    return {"by_meal": by_meal, "by_pdf": by_pdf, "by_variant": by_variant}


def _print_samples(recipes: list[RecipeData], n: int = 3) -> None:
    """Show up to N recipes with embedding text + makro — debug dry-run."""
    for r in recipes[:n]:
        print(  # noqa: T201  # script-only
            f"  - [{r.meal_type}/{r.gender_variant}] {r.name} "
            f"({r.kcal}kcal, P{r.protein_g}g/F{r.fat_g}g/C{r.carbs_g}g, "
            f"{r.prep_minutes}min, ingredients={len(r.ingredients)}, "
            f"steps={len(r.instructions)})"
        )
        print(f"    embedding: {r.embedding_text[:200]}...")  # noqa: T201


def main(argv: list[str] | None = None) -> int:  # noqa: PLR0915 — script orchestration
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else "")
    parser.add_argument("--pdf-dir", type=Path, default=Path("../../samples/recipes/"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--table", default=DEFAULT_TABLE)
    parser.add_argument("--region", default=DEFAULT_REGION)
    parser.add_argument("--limit", type=int, default=None, help="Debug: parse only N PDFs")
    args = parser.parse_args(argv)

    pdf_dir = args.pdf_dir.resolve()
    if not pdf_dir.is_dir():
        logger.error("pdf_dir_not_found path=%s", pdf_dir)
        return 2

    t0 = time.monotonic()
    logger.info("seed_start pdf_dir=%s dry_run=%s", pdf_dir, args.dry_run)

    # 1. Parse all PDFs.
    recipes = parse_all_pdfs(pdf_dir, limit=args.limit)
    recipes = deduplicate(recipes)
    if not recipes:
        logger.error("no_recipes_parsed exit")
        return 1

    # 2. Build embedding text for each recipe.
    for r in recipes:
        r.embedding_text = build_embedding_text(r)

    # 3. Embed via OpenAI (skip in dry-run if no key — defensive).
    embeddings: list[list[float]] = []
    try:
        openai_key = _get_openai_key(args.region)
    except (SystemExit, Exception) as exc:  # noqa: BLE001 — script tolerance
        if args.dry_run:
            logger.warning("openai_key_unavailable dry_run continue err=%s", exc)
            openai_key = ""
        else:
            raise
    if openai_key:
        embeddings = embed_batch([r.embedding_text for r in recipes], openai_key)
    elif args.dry_run:
        logger.info("dry_run skip_embed reason=no_key")

    # 4. Build FAISS index (only if embeddings present).
    index: Any = None
    if embeddings:
        index = build_faiss_index(embeddings)

    # 5. Dry-run summary + samples → exit.
    summary = _summarize(recipes)
    if args.dry_run:
        elapsed = time.monotonic() - t0
        logger.info(
            "dry_run_complete recipes=%d elapsed_s=%.1f summary=%s",
            len(recipes),
            elapsed,
            summary,
        )
        print("\n=== DRY RUN SAMPLES ===")  # noqa: T201
        _print_samples(recipes, n=5)
        print(f"\nTotal: {len(recipes)} recipes parsed.")  # noqa: T201
        print(f"Summary: {json.dumps(summary, ensure_ascii=False, indent=2)}")  # noqa: T201
        return 0

    # 6. Real run — S3 + DDB writes.
    if index is None:
        logger.error("no_faiss_index_real_run abort")
        return 1
    bucket = _resolve_bucket(args.bucket, args.region)
    upload_to_s3(index, recipes, bucket=bucket, region=args.region)
    write_to_ddb(recipes, table_name=args.table, region=args.region)

    elapsed = time.monotonic() - t0
    logger.info(
        "seed_complete recipes=%d bucket=%s table=%s elapsed_s=%.1f summary=%s",
        len(recipes),
        bucket,
        args.table,
        elapsed,
        summary,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
