import { useState } from "react";

interface Props {
  onSend: (text: string) => void;
  disabled?: boolean;
}

export function Composer({ onSend, disabled }: Props): JSX.Element {
  const [value, setValue] = useState("");

  function submit(event: React.FormEvent): void {
    event.preventDefault();
    if (!value.trim()) return;
    onSend(value);
    setValue("");
  }

  return (
    <form className="albert-composer" onSubmit={submit}>
      <input
        type="text"
        className="albert-composer__input"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder="Type a message…"
        aria-label="Message"
        autoComplete="off"
        enterKeyHint="send"
        disabled={disabled}
        maxLength={4000}
      />
      <button
        type="submit"
        className="albert-composer__send"
        disabled={disabled || !value.trim()}
        aria-label="Send message"
      >
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M22 2 11 13" />
          <path d="M22 2 15 22 11 13 2 9z" />
        </svg>
      </button>
    </form>
  );
}
