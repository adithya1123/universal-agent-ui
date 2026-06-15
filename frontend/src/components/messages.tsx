"use client";

import { useEffect, useRef } from "react";
import { Message, AwaitingResponse } from "./message";

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

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto max-w-4xl px-4 py-4">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full min-h-[60vh] text-center">
            <h1 className="text-xl font-semibold text-foreground mb-2">
              What would you like to know?
            </h1>
            <p className="text-sm text-muted-foreground max-w-md">
              Select an agent from the sidebar or type a message to start a conversation.
            </p>
          </div>
        )}
        {messages.map((msg, i) => (
          <Message key={i} role={msg.role} content={msg.content} />
        ))}
        {isStreaming && messages.length > 0 && messages[messages.length - 1].role === "user" && (
          <AwaitingResponse />
        )}
        <div ref={endRef} className="min-h-[24px]" />
      </div>
    </div>
  );
}
