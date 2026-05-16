import { render } from '@testing-library/react';
import { describe, expect, test } from 'vitest';
import { RecipeModal } from '../components/chat/RecipeModal';
import type { RecipeFull } from '../recipes';

const SAMPLE: RecipeFull = {
  slug: 'jajecznica-na-maśle',
  name: 'Jajecznica na maśle',
  meal_type: 'sniadanie',
  prep_minutes: 10,
  difficulty: 'łatwe',
  kcal: 420,
  protein_g: 22,
  fat_g: 32,
  carbs_g: 8,
  fiber_g: 2,
  sodium_mg: 380,
  ingredients: [
    { name: 'jajka', raw: '3 jajka' },
    { name: 'masło', raw: '15 g masła' },
  ],
  instructions: ['Rozgrzej patelnię', 'Wbij jajka'],
  tags: ['quick'],
  source_pdf: 'kuchnia.pdf',
  source_page: 12,
};

describe('RecipeModal', () => {
  test('open → aria-modal="true" + aria-labelledby wskazuje na h2', () => {
    const { container } = render(<RecipeModal recipe={SAMPLE} onClose={() => {}} />);
    const dialog = container.querySelector('[role="dialog"]');
    expect(dialog).not.toBeNull();
    expect(dialog?.getAttribute('aria-modal')).toBe('true');
    const labelledby = dialog?.getAttribute('aria-labelledby');
    expect(labelledby).toBeTruthy();
    const heading = document.getElementById(labelledby!);
    expect(heading?.tagName).toBe('H2');
    expect(heading?.textContent).toBe('Jajecznica na maśle');
  });

  test('open lockuje body scroll; close restore', () => {
    document.body.style.overflow = '';
    const { rerender } = render(<RecipeModal recipe={SAMPLE} onClose={() => {}} />);
    expect(document.body.style.overflow).toBe('hidden');
    rerender(<RecipeModal recipe={null} onClose={() => {}} />);
    expect(document.body.style.overflow).toBe('');
  });

  test('recipe=null → nic nie renderuje, body scroll niedotknięty', () => {
    document.body.style.overflow = 'auto';
    const { container } = render(<RecipeModal recipe={null} onClose={() => {}} />);
    expect(container.querySelector('[role="dialog"]')).toBeNull();
    expect(document.body.style.overflow).toBe('auto');
  });
});
