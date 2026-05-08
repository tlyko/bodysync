import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, chatErrorMessage, postAdvisorChat } from '../../api';
import { getRecipeBySlug, type RecipeFull } from '../../recipes';
import type { ChatMessage as ChatMessageT, UsedRecipe } from '../../types';
import { ChatInput } from './ChatInput';
import { ChatMessage } from './ChatMessage';
import { RecipeModal } from './RecipeModal';

export function ChatScreen() {
  const [messages, setMessages] = useState<ChatMessageT[]>([]);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedRecipe, setSelectedRecipe] = useState<RecipeFull | null>(null);

  const controllerRef = useRef<AbortController | null>(null);
  const threadEndRef = useRef<HTMLDivElement | null>(null);

  // Cleanup abort na unmount — chat call leci dalej w sieci, ale callback NIE
  // strzela do unmounted komponentu (React 19 by ostrzegało).
  useEffect(() => {
    return () => {
      controllerRef.current?.abort();
    };
  }, []);

  // Scroll-to-bottom przy każdym appendzie. `instant` w pierwszym tylko żeby
  // nie animować pustego widoku.
  useEffect(() => {
    threadEndRef.current?.scrollIntoView({ behavior: messages.length <= 1 ? 'auto' : 'smooth' });
  }, [messages]);

  const handleSend = useCallback(
    async (msg: string) => {
      // Optimistic user bubble z `pending=false` (sami wysłaliśmy, nie czekamy
      // na potwierdzenie tego że user typował).
      setMessages((prev) => [...prev, { role: 'user', content: msg, pending: false }]);
      setPending(true);
      setError(null);

      controllerRef.current?.abort();
      const controller = new AbortController();
      controllerRef.current = controller;

      try {
        const dto = await postAdvisorChat({ message: msg }, controller.signal);
        setMessages((prev) => [
          ...prev,
          {
            role: 'assistant',
            content: dto.content,
            used_recipes: dto.used_recipes,
            turn_idx: dto.turn_idx,
          },
        ]);
      } catch (e) {
        if (e instanceof ApiError && e.status === 0) {
          // aborted (component unmount or new send) — ignore
          return;
        }
        setError(chatErrorMessage(e));
        // User wiadomość zostaje w threadzie nawet po błędzie (UX żeby
        // widział co wysłał + mógł retry).
      } finally {
        if (controllerRef.current === controller) {
          setPending(false);
          controllerRef.current = null;
        }
      }
    },
    [],
  );

  const handleRecipeClick = useCallback((recipe: UsedRecipe) => {
    const full = getRecipeBySlug(recipe.slug);
    if (full) {
      setSelectedRecipe(full);
    }
    // Jeśli slug nie ma w lokalnej mapie (recipes.json desync) — nie otwiera
    // modal. RecipeCard widoczna w threadzie z basic info (name, kcal, match).
  }, []);

  return (
    <div className="chat-screen">
      <div className="chat-thread">
        {messages.length === 0 && (
          <div className="chat-thread-empty">
            <p>
              Spróbuj zapytać:
              <br />
              <em>"Co lekkiego na kolację z białkiem?"</em>
              <br />
              <em>"Mam zostawione 600 kcal i 30g białka, co zjeść?"</em>
            </p>
          </div>
        )}
        {messages.map((m, i) => (
          <ChatMessage key={i} message={m} onRecipeClick={handleRecipeClick} />
        ))}
        {pending && (
          <div className="message-row assistant">
            <div className="message-bubble assistant pending">Asystent myśli…</div>
          </div>
        )}
        <div ref={threadEndRef} />
      </div>
      {error && <div className="chat-error">{error}</div>}
      <ChatInput onSend={handleSend} disabled={pending} />
      <RecipeModal recipe={selectedRecipe} onClose={() => setSelectedRecipe(null)} />
    </div>
  );
}
