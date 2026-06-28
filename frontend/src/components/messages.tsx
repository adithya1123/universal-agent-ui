"use client";

import { useEffect, useRef } from "react";
import { Loader2 } from "lucide-react";
import { Message } from "./message";

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export function Messages({
  messages,
  isStreaming,
}: {
  messages: ChatMessage[];
  isStreaming: boolean;
}) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isStreaming]);

  const lastAssistantMsg = [...messages].reverse().find((m) => m.role === "assistant");
  const rawContent = lastAssistantMsg?.content || "";
  const reasoningMatch = rawContent.match(/\[REASONING\]([^\n]*)/);
  const statusText = reasoningMatch ? reasoningMatch[1].trim().slice(0, 100) : null;

  const cleanMessages = messages.map((m) => ({
    ...m,
    content: m.content.replace(/\[REASONING\][^\n]*(\n|$)/g, ""),
  }));

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto max-w-4xl px-4 py-4">
        {messages.length === 0 && !isStreaming && (
          <div className="flex flex-col items-center justify-center h-full min-h-[60vh] text-center">
            <h1 className="text-xl font-semibold text-foreground mb-2">
              What would you like to know?
            </h1>
            <p className="text-sm text-muted-foreground max-w-md">
              Select an agent from the sidebar or type a message to start a conversation.
            </p>
          </div>
        )}
        {cleanMessages.map((msg, i) => (
          <Message key={i} role={msg.role} content={msg.content} />
        ))}
        {isStreaming && (
          <div className="flex items-center gap-2 px-4 py-2 text-xs text-muted-foreground">
            <Loader2 className="size-3 animate-spin text-blue-500 shrink-0" />
            <span className="truncate">
              {statusText || "Agent is responding..."}
            </span>
          </div>
        )}
        <div ref={endRef} className="min-h-[8px]" />
      </div>
    </div>
  );
}
