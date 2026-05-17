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
  // Sprint 11.5 ADR-009 — diet check state. Stare tdee_* attrs (Sprint 11)
  // zostają w DDB jako dead weight, frontend ignoruje.
  diet_check_last?: DietCheckHistoryEntry | null;
  diet_check_history?: DietCheckHistoryEntry[];
};

export type DietCheckSkipReason =
  | 'insufficient_kcal_data'
  | 'insufficient_weight_data'
  | 'weight_anchor_missing'
  | 'weight_now_missing'
  | 'no_kcal_target';

export type DietCheckStatus = 'on_track' | 'too_fast' | 'too_slow_or_gain';

export type DietCheckResult = {
  skipped: boolean;
  skip_reason: DietCheckSkipReason | null;
  goal_kcal: number | null;
  kcal_in_avg: number | null;
  waga_now_kg: number | null;
  waga_then_kg: number | null;
  waga_delta_kg: number | null;
  expected_delta_kg: number | null;
  actual_delta_kg: number | null;
  diff_kg: number | null;
  status: DietCheckStatus | null;
  narrative: string | null;
  narrative_unavailable: boolean;
};

export type DietCheckHistoryEntry = {
  date: string;
  skipped: boolean;
  skip_reason: DietCheckSkipReason | null;
  goal_kcal: number | null;
  kcal_in_avg: number | null;
  waga_delta_kg: number | null;
  diff_kg: number | null;
  status: DietCheckStatus | null;
  narrative: string | null;
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

// ─── Workout history (2026-05-17, mirror handlers/workouts_extract/schemas.py) ───

export type WorkoutSet = {
  weight_kg?: number | null;
  weight_kind: 'kg' | 'bw' | 'other';
  reps: number;
};

export type WorkoutEntry = {
  date: string;
  training_slug: string;
  training_name: string;
  exercise_number: string;
  exercise_name: string;
  sets: WorkoutSet[];
  rir?: number | null;
  notes?: string | null;
  source?: string;
  recorded_at?: number;
};

export type WorkoutsResponse = {
  workouts: WorkoutEntry[];
};

export type WorkoutExtractRequest = {
  today_iso: string;
  trainings: unknown[]; // mirror Training[] z planParser — opaque payload (forward as-is)
};

export type WorkoutExtractResponse = {
  extracted: number;
  skipped: number;
  errors: number;
  items: Array<{
    date: string;
    training_name: string;
    exercise_number: string;
    exercise_name: string;
    sets: WorkoutSet[];
    rir?: number | null;
    notes?: string | null;
  }>;
};

// ─── Body measurements (Sprint 12, mirror handlers/measurements/schemas.py) ───

export type MeasurementsRequest = {
  date: string; // YYYY-MM-DD
  // Body measurements (cm).
  waist_cm?: number | null;
  hips_cm?: number | null;
  chest_cm?: number | null;
  biceps_cm?: number | null;
  thigh_cm?: number | null;
  // Nutrition manual entry (override HAE dla danego dnia, post-Recovery sprint).
  kcal_in?: number | null;
  protein_g?: number | null;
  fat_g?: number | null;
  carbs_g?: number | null;
};

export type MeasurementsResponse = {
  saved: string[];
  date: string;
};

// ─── Waitlist landing (PR1 backend mirror — handlers/waitlist/schemas.py) ───

export type WaitlistSignupRequest = {
  email: string;
  consent: boolean;
  honeypot: string;
  interest: string | null;
};
