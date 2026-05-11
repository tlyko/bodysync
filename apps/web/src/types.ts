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

// ─── Sprint 10 A1 — chat history GET (mirror handlers/advisor_chat/schemas.py) ───

export type ChatHistoryEntry = {
  role: 'user' | 'assistant';
  content: string;
  turn_idx: number;
  ts: string;
};

export type ChatHistoryResponse = {
  messages: ChatHistoryEntry[];
  date: string; // YYYY-MM-DD
};

// ─── Profile targets (Sprint 9, mirror schemas.py — Sprint 10 A0 extended) ───

export type ActivityLevel = 'sedentary' | 'light' | 'moderate' | 'heavy' | 'athlete';
export type Sex = 'male' | 'female';
export type Goal = 'loss' | 'maintain' | 'gain';

export type BodyProfile = {
  height_cm: number;
  age: number;
  sex: Sex;
  activity_level: ActivityLevel;
  goal: Goal;
};

export type ProfileTargets = {
  kcal_target: number;
  protein_target_g: number;
  fat_target_g: number;
  carbs_target_g: number;
  is_default: boolean;
  body_profile: BodyProfile | null;
  // Sprint 11 — adaptive TDEE state (read-only, init przez body_profile save
  // w PR4, update przez tdee_recalc Lambda PR2/PR3 cron + manual button PR5).
  tdee_baseline?: number | null;
  tdee_adaptive?: number | null;
  tdee_last_recalc?: RecalcHistoryEntry | null;
  tdee_history?: RecalcHistoryEntry[];
};

export type RecalcSkipReason =
  | 'insufficient_kcal_data'
  | 'insufficient_weight_data'
  | 'weight_anchor_missing'
  | 'weight_now_missing'
  | 'kcal_in_avg_unrealistic'
  | 'baseline_not_initialized';

export type RecalcResult = {
  ok: boolean;
  skipped: boolean;
  reason: RecalcSkipReason | null;
  tdee_before: number;
  tdee_after: number;
  kcal_in_avg: number | null;
  waga_delta_kg: number | null;
  adjustment: number | null;
  capped: boolean;
};

export type RecalcHistoryEntry = {
  date: string;
  event: 'recalc' | 'body_profile_change' | 'skipped' | 'initial';
  before: number | null;
  after: number | null;
  kcal_in_avg: number | null;
  waga_delta_kg: number | null;
  adjustment: number | null;
  capped: boolean;
  reason: string | null;
};

export type ProfileTargetsUpdate = {
  kcal_target: number;
  protein_target_g: number;
  fat_target_g: number;
  carbs_target_g: number;
  body_profile?: BodyProfile;
};

// ─── Sprint 10 A0 — TDEE calculator (POST /api/profile/calculate-tdee) ───

export type CalculateTDEERequest = {
  body_profile?: BodyProfile;
  weight_kg?: number;
};

export type CalculateTDEEResponse = {
  bmr: number;
  tdee_maintenance: number;
  target_kcal: number;
  target_protein_g: number;
  target_fat_g: number;
  target_carbs_g: number;
  weight_kg_used: number;
};

// ─── Sprint 10 A0.5 — LLM-driven activity level suggestion ───

export type ActivitySuggestionResponse = {
  level: ActivityLevel;
  reasoning: string;
  activities_count: number;
  avg_steps: number | null;
  avg_kcal_active: number | null;
};

// ─── Activities (Sprint 4, mirror handlers/activities_list) ───

export type Activity = {
  strava_id: number;
  name: string;
  sport_type: string; // Strava enum: Run / Ride / Walk / Swim / Hike / etc.
  type: string;
  distance_m: number;
  moving_time_s: number;
  elapsed_time_s: number;
  elevation_gain_m: number;
  start_date: string; // ISO 8601 UTC
  start_date_local: string; // ISO 8601 lokalny
  calories: number | null;
  average_heartrate: number | null;
  max_heartrate: number | null;
  // Sprint 10 A9 — Google Encoded Polyline (low-resolution summary).
  // Null gdy sport bez GPS (WeightTraining, Yoga) lub aktywność pre-A9
  // (fetcher zaczął zapisywać dopiero w PR #140).
  summary_polyline: string | null;
};

export type ActivitiesResponse = {
  items: Activity[];
};

// ─── Plan (Sprint 5 — Google Sheets training plan, mirror handlers/plan/schemas.py) ───

export type PlanResponse = {
  rows: string[][]; // 2D array, sheet content as-is (raw text)
  fetched_at: number; // epoch seconds
  fresh: boolean; // true = just fetched z Sheets, false = z DDB cache
  sheet_tab: string;
};
