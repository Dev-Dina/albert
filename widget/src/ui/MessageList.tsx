import { useEffect, useRef } from "react";

interface Message {
  id: string;
  author: "user" | "assistant";
  text: string;
}

interface Props {
  messages: Message[];
  pending?: boolean;
}

export function MessageList({ messages, pending }: Props): JSX.Element {
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length, pending]);
  return (
    <div className="albert-messages" role="log" aria-live="polite" aria-atomic="false">
      {messages.map((m) => (
        <div
          key={m.id}
          className={`albert-message albert-message--${m.author}`}
          aria-label={m.author === "user" ? "You said" : "Assistant said"}
        >
          {m.text}
        </div>
      ))}
      {pending && (
        <div className="albert-typing" aria-label="Assistant is typing">
          <span className="albert-typing__dot" />
          <span className="albert-typing__dot" />
          <span className="albert-typing__dot" />
        </div>
      )}
      <div ref={endRef} />
    </div>
  );
}
