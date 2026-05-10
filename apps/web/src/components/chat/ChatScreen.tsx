import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ApiError,
  chatErrorMessage,
  deleteChatHistory,
  getChatHistory,
  postAdvisorChat,
} from '../../api';
import { getRecipeBySlug, type RecipeFull } from '../../recipes';
import type {
  ChatHistoryEntry,
  ChatMessage as ChatMessageT,
  UsedRecipe,
} from '../../types';
import { ChatInput } from './ChatInput';
import { ChatMessage } from './ChatMessage';
import { RecipeModal } from './RecipeModal';

// Sprint 10 A4 — suggested prompts dla new user / fresh day. Pokazane
// tylko gdy thread pusty (po hydrate). Owner klika chip → ten tekst leci
// jako pierwszy user message przez handleSend. Treść celuje na typowe
// pytania których owner mógłby się dopytywać (śniadanie po treningu,
// makro coverage, lekka kolacja).
const SUGGESTED_PROMPTS: string[] = [
  'Co lekkiego na kolację z białkiem?',
  'Mam zostawione 600 kcal i 30g białka, co zjeść?',
  'Zaproponuj śniadanie wysokoproteinowe',
  'Co po treningu na regenerację?',
  'Szybki obiad do 30 minut',
  'Kolacja na deficyt 500 kcal',
];

// Sprint 10 A1 — backend ChatHistoryEntry → frontend UI state. used_recipes
// brak w DDB historii (LLM-call-time only), więc po hydrate recipe karty
// NIE są klikalne. Owner widzi treść rozmowy; przez nową wiadomość dostaje
// świeże recipes z RAG retrieval w response.
function entryToMessage(entry: ChatHistoryEntry): ChatMessageT {
  if (entry.role === 'user') {
    return { role: 'user', content: entry.content, pending: false };
  }
  return {
    role: 'assistant',
    content: entry.content,
    used_recipes: [],
    turn_idx: entry.turn_idx,
  };
}

export function ChatScreen() {
  const [messages, setMessages] = useState<ChatMessageT[]>([]);
  const [pending, setPending] = useState(false);
  const [hydrating, setHydrating] = useState(true);
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

  // Hydrate na mount — restore today's chat z DDB (24h TTL). Bez tego
  // refresh strony = pusty thread mimo że backend wciąż pamięta historię.
  // Race-safe: jeśli user zdąży wpisać wiadomość zanim hydrate zwróci
  // (typowo <300ms ale możliwe), NIE nadpisujemy local state — funkcyjny
  // setMessages sprawdza prev.length === 0.
  useEffect(() => {
    let cancelled = false;
    getChatHistory()
      .then((res) => {
        if (cancelled) return;
        setMessages((prev) => (prev.length === 0 ? res.messages.map(entryToMessage) : prev));
      })
      .catch(() => {
        // 401/sieć — UI nie blokuje, owner zacznie nową rozmowę.
        // Jawnego błędu nie pokazujemy żeby nie straszyć (history fetch
        // jest "best effort restore", brak go = empty thread fallback OK).
      })
      .finally(() => {
        if (cancelled) return;
        setHydrating(false);
      });
    return () => {
      cancelled = true;
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

  // Wyczyść rozmowę — confirm → DELETE backend → local reset. Idempotent
  // backend (zwraca 200 nawet gdy brak rows), więc nawet race condition
  // (clear w trakcie pending chat call) nie crashuje UI; pending response
  // wpadnie do pustego thread'a co OK (NIE odtwarzamy bo poprzednia tura
  // została właśnie wymazana).
  const handleClear = useCallback(async () => {
    if (!window.confirm('Wyczyścić dzisiejszą rozmowę? Tego nie cofniesz.')) return;
    controllerRef.current?.abort();
    setError(null);
    try {
      await deleteChatHistory();
      setMessages([]);
    } catch (e) {
      setError(chatErrorMessage(e));
    }
  }, []);

  return (
    <div className="chat-screen">
      {!hydrating && messages.length > 0 && (
        <div className="chat-header">
          <button
            type="button"
            className="chat-clear-btn"
            onClick={handleClear}
            disabled={pending}
            aria-label="Wyczyść rozmowę"
          >
            Wyczyść rozmowę
          </button>
        </div>
      )}
      <div className="chat-thread">
        {hydrating && (
          <div className="chat-thread-empty">
            <p>Wczytywanie rozmowy…</p>
          </div>
        )}
        {!hydrating && messages.length === 0 && (
          <div className="chat-thread-empty">
            <p className="chat-suggestions-intro">Spróbuj zapytać:</p>
            <div className="chat-suggestions">
              {SUGGESTED_PROMPTS.map((prompt) => (
                <button
                  key={prompt}
                  type="button"
                  className="chat-suggestion-chip"
                  onClick={() => handleSend(prompt)}
                  disabled={pending}
                >
                  {prompt}
                </button>
              ))}
            </div>
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
