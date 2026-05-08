import type { UsedRecipe } from '../../types';

type Props = {
  recipe: UsedRecipe;
  onClick: () => void;
};

export function RecipeCard({ recipe, onClick }: Props) {
  const matchPct = Math.round(recipe.similarity_score * 100);
  return (
    <button type="button" className="recipe-card" onClick={onClick}>
      <span className="recipe-card-name">{recipe.name}</span>
      <span className="recipe-card-meta">
        <span className="recipe-card-kcal">{recipe.kcal} kcal</span>
        <span className="recipe-card-match">match {matchPct}%</span>
      </span>
    </button>
  );
}
