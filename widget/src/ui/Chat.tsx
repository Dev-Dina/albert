import { useState } from "react";
import type { WidgetPublicView } from "../api";
import { sendChat } from "../api";
import { MessageList } from "./MessageList";
import { Composer } from "./Composer";

interface Message {
  id: string;
  author: "user" | "assistant";
  text: string;
}

interface Props {
  widget: WidgetPublicView;
}

function getInitial(view: WidgetPublicView): string {
  const themed = (view.theme as Record<string, unknown>)?.title;
  if (typeof themed === "string" && themed.length > 0) return themed[0]!.toUpperCase();
  return "A";
}

function getTitle(view: WidgetPublicView): string {
  const themed = (view.theme as Record<string, unknown>)?.title;
  return typeof themed === "string" && themed.length > 0 ? themed : "Albert";
}

export function Chat({ widget }: Props): JSX.Element {
  const [messages, setMessages] = useState<Message[]>(() => {
    if (!widget.greeting) return [];
    return [{ id: "greeting", author: "assistant", text: widget.greeting }];
  });
  const [conversationId, setConversationId] = useState<string | undefined>();
  const [pending, setPending] = useState(false);

  async function handleSend(text: string): Promise<void> {
    const trimmed = text.trim();
    if (!trimmed || pending) return;
    const userMessage: Message = {
      id: `u-${Date.now()}`,
      author: "user",
      text: trimmed,
    };
    setMessages((prev) => [...prev, userMessage]);
    setPending(true);
    try {
      const response = await sendChat({
        message: trimmed,
        conversation_id: conversationId,
      });
      setConversationId(response.conversation_id);
      setMessages((prev) => [
        ...prev,
        {
          id: `a-${Date.now()}`,
          author: "assistant",
          text: response.message,
        },
      ]);
    } catch {
      setMessages((prev) => [
        ...prev,
        {
          id: `e-${Date.now()}`,
          author: "assistant",
          text: "Session expired — please refresh the page.",
        },
      ]);
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="albert-chat" data-widget-id={widget.public_widget_id}>
      <header className="albert-header">
        <div className="albert-avatar" aria-hidden="true">
          {getInitial(widget)}
        </div>
        <div className="albert-header__info">
          <span className="albert-header__title">{getTitle(widget)}</span>
          <span className="albert-header__status">Online</span>
        </div>
      </header>
      <MessageList messages={messages} pending={pending} />
      <Composer onSend={handleSend} disabled={pending} />
    </div>
  );
}
