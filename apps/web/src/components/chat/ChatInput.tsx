import { type KeyboardEvent, useState } from 'react';

type Props = {
  onSend: (msg: string) => void;
  disabled: boolean;
};

const MAX_CHARS = 2000;
const WARN_AT = 1800;

export function ChatInput({ onSend, disabled }: Props) {
  const [value, setValue] = useState('');

  const trimmed = value.trim();
  const canSend = trimmed.length > 0 && !disabled && trimmed.length <= MAX_CHARS;

  const handleSend = () => {
    if (!canSend) return;
    onSend(trimmed);
    setValue('');
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const overWarn = value.length >= WARN_AT;

  return (
    <div className="chat-input">
      <label htmlFor="chat-input-textarea" className="sr-only">
        Wiadomość do asystenta AI
      </label>
      <textarea
        id="chat-input-textarea"
        className="chat-input-textarea"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Napisz wiadomość… (Enter wysyła, Shift+Enter nowa linia)"
        rows={3}
        disabled={disabled}
        maxLength={MAX_CHARS}
      />
      <div className="chat-input-row">
        <span className={`chat-input-counter ${overWarn ? 'warn' : ''}`}>
          {value.length}/{MAX_CHARS}
        </span>
        <button
          type="button"
          className="chat-input-send"
          onClick={handleSend}
          disabled={!canSend}
        >
          {disabled ? 'Czekam…' : 'Wyślij'}
        </button>
      </div>
    </div>
  );
}
