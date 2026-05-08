// TypeScript types odpowiadające Pydantic schemas w apps/api/handlers/.
// Przy zmianie schemas → zaktualizuj tutaj (TODO: codegen z OpenAPI w przyszłości).

export type Me = {
  user_id: string;
  email: string;
  name: string | null;
};

export type BiometryDay = {
  date: string; // YYYY-MM-DD
  metrics: Record<string, BiometryValue | BiometryValue[]>;
};

export type BiometryValue = Record<string, number | string | null>;

export type BiometryResponse = {
  days: BiometryDay[];
};

export type LoginResponse = {
  user_id: string;
  email: string;
  name: string | null;
};

// ─── Advisor chat (Sprint 7, mirror apps/api/handlers/advisor_chat/schemas.py) ───

export type UsedRecipe = {
  slug: string;
  name: string;
  kcal: number;
  similarity_score: number;
};

export type TokenUsage = {
  input_tokens: number;
  output_tokens: number;
  cache_read_input_tokens: number;
  cache_creation_input_tokens: number;
};

export type ChatMessageDTO = {
  role: 'user' | 'assistant';
  content: string;
  used_recipes: UsedRecipe[];
  turn_idx: number;
  tokens_used: TokenUsage;
  generated_at: string;
};

export type ChatRequest = {
  message: string;
  conversation_date?: string; // YYYY-MM-DD UTC; default = today
};

// Local UI state — user message stub (pending=true) lub assistant response.
// Tokens/generated_at pomijane w UI — bez biznesowej wartości dla usera.
export type ChatMessage =
  | { role: 'user'; content: string; pending: boolean }
  | { role: 'assistant'; content: string; used_recipes: UsedRecipe[]; turn_idx: number };
