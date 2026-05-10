import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { ApiError } from '../api';
import { ChatScreen } from '../components/chat/ChatScreen';
import type { ChatMessageDTO } from '../types';

// Mock api module — kontroluemy postAdvisorChat + getChatHistory per test.
vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api');
  return {
    ...actual,
    postAdvisorChat: vi.fn(),
    getChatHistory: vi.fn(),
  };
});

// Mock recipes — getRecipeBySlug zwraca sample RecipeFull dla modal test.
vi.mock('../recipes', () => ({
  getRecipeBySlug: vi.fn((slug: string) => {
    if (slug === 'kolacja-przepis-1') {
      return {
        slug: 'kolacja-przepis-1',
        name: 'Sample Recipe',
        meal_type: 'kolacja',
        kcal: 450,
        protein_g: 30,
        fat_g: 15,
        carbs_g: 40,
        ingredients: [{ name: 'Kurczak', raw: 'Kurczak 200g' }],
        instructions: ['Krok 1', 'Krok 2'],
        source_pdf: 'najszybsze-kolacje.pdf',
        source_page: 12,
        tags: ['BIALKO'],
      };
    }
    return undefined;
  }),
  RECIPE_COUNT: 1,
}));

import { getChatHistory, postAdvisorChat } from '../api';

const mockPostAdvisorChat = vi.mocked(postAdvisorChat);
const mockGetChatHistory = vi.mocked(getChatHistory);

function makeDto(overrides: Partial<ChatMessageDTO> = {}): ChatMessageDTO {
  return {
    role: 'assistant',
    content: 'Polecam **kurczaka**.',
    used_recipes: [
      {
        slug: 'kolacja-przepis-1',
        name: 'Sample Recipe',
        kcal: 450,
        similarity_score: 0.85,
      },
    ],
    turn_idx: 1,
    tokens_used: {
      input_tokens: 10,
      output_tokens: 20,
      cache_read_input_tokens: 0,
      cache_creation_input_tokens: 0,
    },
    generated_at: '2026-05-08T12:00:00+00:00',
    ...overrides,
  };
}

beforeEach(() => {
  // jsdom nie ma scrollIntoView — ChatScreen używa go w useEffect.
  Element.prototype.scrollIntoView = vi.fn();
  // Default: empty chat history (każdy test może override).
  mockGetChatHistory.mockReset();
  mockGetChatHistory.mockResolvedValue({ messages: [], date: '2026-05-10' });
});

afterEach(() => {
  vi.clearAllMocks();
});

describe('ChatScreen', () => {
  test('happy path: wysyła wiadomość, renderuje assistant + recipe card', async () => {
    mockPostAdvisorChat.mockResolvedValueOnce(makeDto());
    render(<ChatScreen />);

    const textarea = screen.getByPlaceholderText(/Napisz wiadomość/);
    fireEvent.change(textarea, { target: { value: 'co na kolacje' } });
    fireEvent.click(screen.getByRole('button', { name: /Wyślij/i }));

    // User bubble appears immediately
    expect(screen.getByText('co na kolacje')).toBeInTheDocument();

    // Assistant response after promise resolves — markdown rendered
    await waitFor(() => {
      expect(screen.getByText(/Polecam/)).toBeInTheDocument();
    });

    // Recipe card present
    expect(screen.getByRole('button', { name: /Sample Recipe/i })).toBeInTheDocument();
    expect(mockPostAdvisorChat).toHaveBeenCalledWith(
      { message: 'co na kolacje' },
      expect.any(AbortSignal),
    );
  });

  test('429 quota: error banner z PL message', async () => {
    mockPostAdvisorChat.mockRejectedValueOnce(new ApiError(429, 'rate limit'));
    render(<ChatScreen />);

    fireEvent.change(screen.getByPlaceholderText(/Napisz/), { target: { value: 'pytanie' } });
    fireEvent.click(screen.getByRole('button', { name: /Wyślij/i }));

    await waitFor(() => {
      expect(screen.getByText(/dzienny limit/i)).toBeInTheDocument();
    });
    // User bubble zostaje (UX retry)
    expect(screen.getByText('pytanie')).toBeInTheDocument();
  });

  test('401 reauth: error banner sugerujący login', async () => {
    mockPostAdvisorChat.mockRejectedValueOnce(new ApiError(401, 'no jwt'));
    render(<ChatScreen />);

    fireEvent.change(screen.getByPlaceholderText(/Napisz/), { target: { value: 'pytanie' } });
    fireEvent.click(screen.getByRole('button', { name: /Wyślij/i }));

    await waitFor(() => {
      expect(screen.getByText(/Sesja wygasła/i)).toBeInTheDocument();
    });
  });

  test('pending: input + button disabled podczas request', async () => {
    // Promise nigdy się nie resolve'uje — observujemy pending state.
    // Po teście ChatScreen unmount → useEffect cleanup wywoła
    // controllerRef.abort() → ApiError(0) zignorowane.
    mockPostAdvisorChat.mockReturnValueOnce(new Promise(() => {}));
    const { unmount } = render(<ChatScreen />);

    const textarea = screen.getByPlaceholderText(/Napisz/) as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: 'pytanie' } });
    fireEvent.click(screen.getByRole('button', { name: /Wyślij/i }));

    await waitFor(() => {
      expect(textarea.disabled).toBe(true);
    });
    expect(screen.getByRole('button', { name: /Czekam/i })).toBeDisabled();
    expect(screen.getByText(/Asystent myśli/i)).toBeInTheDocument();

    unmount();
  });

  test('hydrate na mount: pre-existing history wypełnia thread', async () => {
    mockGetChatHistory.mockResolvedValueOnce({
      messages: [
        { role: 'user', content: 'Co na obiad?', turn_idx: 0, ts: '2026-05-10T10:00:00+00:00' },
        {
          role: 'assistant',
          content: 'Polecam **łososia**.',
          turn_idx: 1,
          ts: '2026-05-10T10:00:01+00:00',
        },
      ],
      date: '2026-05-10',
    });
    render(<ChatScreen />);

    await waitFor(() => {
      expect(screen.getByText('Co na obiad?')).toBeInTheDocument();
    });
    expect(screen.getByText(/Polecam/)).toBeInTheDocument();
    // Empty-state CTA NIE pokazane gdy historia istnieje
    expect(screen.queryByText(/Spróbuj zapytać/)).not.toBeInTheDocument();
  });

  test('hydrate fail: nie blokuje empty state CTA', async () => {
    mockGetChatHistory.mockRejectedValueOnce(new ApiError(401, 'no jwt'));
    render(<ChatScreen />);

    await waitFor(() => {
      expect(screen.getByText(/Spróbuj zapytać/)).toBeInTheDocument();
    });
  });

  test('recipe card click: otwiera modal z full RecipeFull', async () => {
    mockPostAdvisorChat.mockResolvedValueOnce(makeDto());
    render(<ChatScreen />);

    fireEvent.change(screen.getByPlaceholderText(/Napisz/), { target: { value: 'q' } });
    fireEvent.click(screen.getByRole('button', { name: /Wyślij/i }));

    const card = await screen.findByRole('button', { name: /Sample Recipe/i });
    fireEvent.click(card);

    // Modal heading
    await waitFor(() => {
      expect(screen.getByRole('dialog')).toBeInTheDocument();
    });
    expect(screen.getByRole('heading', { level: 2, name: 'Sample Recipe' })).toBeInTheDocument();
    // Macro values
    expect(screen.getByText('Kcal')).toBeInTheDocument();
    expect(screen.getByText('Białko')).toBeInTheDocument();
    // Ingredient
    expect(screen.getByText('Kurczak 200g')).toBeInTheDocument();
    // Source attribution
    expect(screen.getByText(/najszybsze-kolacje\.pdf · str\. 12/)).toBeInTheDocument();

    // Close via ESC
    fireEvent.keyDown(window, { key: 'Escape' });
    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
  });
});
