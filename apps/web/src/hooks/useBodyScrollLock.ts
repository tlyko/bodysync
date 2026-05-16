import { useEffect } from 'react';

// Block body scroll while a modal is open. Without this, swipe on mobile or
// wheel-over the overlay drags the underlying page — UX gap zgłoszony w
// docs/audit-2026-05-16.md (RecipeModal + DemoGallery overlay scrolling).
export function useBodyScrollLock(open: boolean) {
  useEffect(() => {
    if (!open) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = previous;
    };
  }, [open]);
}
