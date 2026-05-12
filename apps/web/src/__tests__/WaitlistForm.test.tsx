import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { ApiError } from '../api';
import { WaitlistForm } from '../components/WaitlistForm';

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api');
  return {
    ...actual,
    postWaitlist: vi.fn(),
  };
});

import { postWaitlist } from '../api';

const mockPost = vi.mocked(postWaitlist);

beforeEach(() => {
  mockPost.mockReset();
});

afterEach(() => {
  vi.clearAllMocks();
});

const fillForm = (opts: { email?: string; interest?: string; consent?: boolean }) => {
  if (opts.email !== undefined) {
    fireEvent.change(screen.getByLabelText(/Adres email/i), { target: { value: opts.email } });
  }
  if (opts.interest !== undefined) {
    fireEvent.change(screen.getByLabelText(/Czego najbardziej oczekujesz/i), {
      target: { value: opts.interest },
    });
  }
  if (opts.consent) {
    fireEvent.click(screen.getByRole('checkbox'));
  }
};

describe('WaitlistForm', () => {
  test('happy path: submits with interest=null and shows success', async () => {
    mockPost.mockResolvedValueOnce({ ok: true });
    render(<WaitlistForm />);
    fillForm({ email: 'tomek@example.com', consent: true });
    fireEvent.click(screen.getByRole('button', { name: /Zapisz mnie/i }));

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith({
        email: 'tomek@example.com',
        consent: true,
        honeypot: '',
        interest: null,
      });
    });
    expect(await screen.findByText(/Dzięki! Odezwę się/i)).toBeInTheDocument();
  });

  test('submit with interest text persists trimmed value in payload', async () => {
    mockPost.mockResolvedValueOnce({ ok: true });
    render(<WaitlistForm />);
    fillForm({
      email: 'a@b.pl',
      interest: '  plany żywieniowe  ',
      consent: true,
    });
    fireEvent.click(screen.getByRole('button', { name: /Zapisz mnie/i }));

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith(
        expect.objectContaining({ interest: 'plany żywieniowe' }),
      );
    });
  });

  test('invalid email shows inline error and does NOT submit', async () => {
    render(<WaitlistForm />);
    fillForm({ email: 'notanemail', consent: true });
    fireEvent.click(screen.getByRole('button', { name: /Zapisz mnie/i }));

    expect(await screen.findByText(/prawidłowy adres email/i)).toBeInTheDocument();
    expect(mockPost).not.toHaveBeenCalled();
  });

  test('missing consent disables submit button', () => {
    render(<WaitlistForm />);
    fillForm({ email: 'a@b.pl' });
    expect(screen.getByRole('button', { name: /Zapisz mnie/i })).toBeDisabled();
  });

  test('shows error banner on 422 server response', async () => {
    mockPost.mockRejectedValueOnce(new ApiError(422, 'validation_failed'));
    render(<WaitlistForm />);
    fillForm({ email: 'a@b.pl', consent: true });
    fireEvent.click(screen.getByRole('button', { name: /Zapisz mnie/i }));

    expect(await screen.findByText(/Sprawdź email i zgodę/i)).toBeInTheDocument();
    expect(screen.queryByText(/Dzięki!/i)).not.toBeInTheDocument();
  });

  test('shows network banner on ApiError -1', async () => {
    mockPost.mockRejectedValueOnce(new ApiError(-1, 'network'));
    render(<WaitlistForm />);
    fillForm({ email: 'a@b.pl', consent: true });
    fireEvent.click(screen.getByRole('button', { name: /Zapisz mnie/i }));

    expect(await screen.findByText(/Brak połączenia/i)).toBeInTheDocument();
  });

  test('honeypot is rendered off-screen but accessible to bot fill', () => {
    const { container } = render(<WaitlistForm />);
    const honeypot = container.querySelector('input[name="phone"]') as HTMLInputElement;
    expect(honeypot).toBeTruthy();
    expect(honeypot.getAttribute('aria-hidden')).toBe('true');
    expect(honeypot.tabIndex).toBe(-1);
  });

  test('interest character counter shows current length', () => {
    render(<WaitlistForm />);
    fillForm({ interest: 'abc' });
    expect(screen.getByText('3/500')).toBeInTheDocument();
  });
});
