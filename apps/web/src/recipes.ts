// Lokalna mapa slug → RecipeFull dla RecipeCard/RecipeModal w chacie.
// Backend `POST /api/advisor/chat` zwraca `used_recipes` z slug+name+kcal —
// frontend matchuje slug w mapie i pokazuje pełne metadane (ingredients,
// instructions, makro) bez round-trip.
//
// Plik `recipes.json` generowany przez `apps/api/scripts/export_recipes_frontend.py`
// z DDB `PK=RECIPES`. Re-run idempotent (sortowanie po slug, ensure_ascii=False).

import recipesData from './recipes.json';

export type RecipeIngredient = {
  name: string;
  raw: string;
  quantity?: number;
  unit?: string;
  serving?: string;
};

export type RecipeFull = {
  slug: string;
  name: string;
  meal_type: string;
  gender_variant?: string;
  kcal: number;
  protein_g: number;
  fat_g: number;
  carbs_g: number;
  fiber_g?: number;
  sodium_mg?: number;
  ingredients: RecipeIngredient[];
  instructions: string[];
  source_pdf: string;
  source_page: number;
  prep_minutes?: number;
  servings?: number;
  difficulty?: string;
  tags?: string[];
};

const recipesMap: Record<string, RecipeFull> = Object.fromEntries(
  (recipesData as RecipeFull[]).map((r) => [r.slug, r]),
);

export function getRecipeBySlug(slug: string): RecipeFull | undefined {
  return recipesMap[slug];
}

export const RECIPE_COUNT = (recipesData as RecipeFull[]).length;
