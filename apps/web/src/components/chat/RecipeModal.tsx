import { useEffect } from 'react';
import type { RecipeFull } from '../../recipes';

type Props = {
  recipe: RecipeFull | null;
  onClose: () => void;
};

const MEAL_TYPE_LABELS: Record<string, string> = {
  sniadanie: 'Śniadanie',
  obiad: 'Obiad',
  kolacja: 'Kolacja',
  deser: 'Deser',
  przekaska: 'Przekąska',
};

export function RecipeModal({ recipe, onClose }: Props) {
  useEffect(() => {
    if (!recipe) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [recipe, onClose]);

  if (!recipe) return null;

  const mealLabel = MEAL_TYPE_LABELS[recipe.meal_type] ?? recipe.meal_type;
  const variantLabel =
    recipe.gender_variant === 'kobiety'
      ? 'wersja dla kobiet'
      : recipe.gender_variant === 'mezczyzni'
        ? 'wersja dla mężczyzn'
        : null;

  return (
    <div className="recipe-modal-overlay" onClick={onClose}>
      <div className="recipe-modal" onClick={(e) => e.stopPropagation()} role="dialog">
        <button type="button" className="recipe-modal-close" onClick={onClose} aria-label="Zamknij">
          ×
        </button>
        <h2 className="recipe-modal-name">{recipe.name}</h2>
        <p className="recipe-modal-subtitle">
          {mealLabel}
          {variantLabel && ` · ${variantLabel}`}
          {recipe.prep_minutes && ` · ${recipe.prep_minutes} min`}
          {recipe.difficulty && ` · ${recipe.difficulty}`}
        </p>

        <div className="recipe-modal-macros">
          <Macro label="Kcal" value={recipe.kcal} unit="kcal" accent="cyan" />
          <Macro label="Białko" value={recipe.protein_g} unit="g" accent="green" />
          <Macro label="Tłuszcz" value={recipe.fat_g} unit="g" accent="orange" />
          <Macro label="Węgle" value={recipe.carbs_g} unit="g" accent="purple" />
          {recipe.fiber_g != null && (
            <Macro label="Błonnik" value={recipe.fiber_g} unit="g" accent="muted" />
          )}
          {recipe.sodium_mg != null && (
            <Macro label="Sód" value={recipe.sodium_mg} unit="mg" accent="muted" />
          )}
        </div>

        <section className="recipe-modal-section">
          <h3>Składniki</h3>
          <ul className="recipe-modal-ingredients">
            {recipe.ingredients.map((ing, i) => (
              <li key={i}>{ing.raw}</li>
            ))}
          </ul>
        </section>

        <section className="recipe-modal-section">
          <h3>Sposób przygotowania</h3>
          <ol className="recipe-modal-instructions">
            {recipe.instructions.map((step, i) => (
              <li key={i}>{step}</li>
            ))}
          </ol>
        </section>

        {recipe.tags && recipe.tags.length > 0 && (
          <div className="recipe-modal-tags">
            {recipe.tags.map((t) => (
              <span key={t} className="recipe-modal-tag">
                {t}
              </span>
            ))}
          </div>
        )}

        <p className="recipe-modal-source">
          Źródło: {recipe.source_pdf} · str. {recipe.source_page}
        </p>
      </div>
    </div>
  );
}

type MacroProps = {
  label: string;
  value: number;
  unit: string;
  accent: 'cyan' | 'green' | 'orange' | 'purple' | 'muted';
};

function Macro({ label, value, unit, accent }: MacroProps) {
  return (
    <div className={`recipe-macro recipe-macro-${accent}`}>
      <span className="recipe-macro-label">{label}</span>
      <span className="recipe-macro-value">
        {value}
        <span className="recipe-macro-unit"> {unit}</span>
      </span>
    </div>
  );
}
