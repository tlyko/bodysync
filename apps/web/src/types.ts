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
