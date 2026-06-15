"use client";

import { cn } from "@/lib/utils";

interface MessageProps {
  role: "user" | "assistant";
  content: string;
  isLoading?: boolean;
}

export function Message({ role, content, isLoading }: MessageProps) {
  if (role === "user") {
    return (
      <div className="flex justify-end mb-4">
        <div className="max-w-[70%] bg-secondary text-secondary-foreground rounded-2xl px-4 py-2.5 text-sm leading-relaxed whitespace-pre-wrap">
          {content}
        </div>
      </div>
    );
  }

  return (
    <div className="flex mb-4">
      <div className="max-w-full px-0 py-0 text-sm leading-relaxed whitespace-pre-wrap">
        {isLoading && !content ? (
          <span className="inline-block bg-ai-gradient rounded-md w-24 h-4 animate-shimmer-text bg-[length:200%_100%]" />
        ) : (
          content
        )}
      </div>
    </div>
  );
}

export function AwaitingResponse() {
  return (
    <div className="flex items-center gap-3 py-4 text-sm text-muted-foreground">
      <span className="flex gap-1">
        <span className="size-1.5 rounded-full bg-muted-foreground/40 animate-bounce" style={{ animationDelay: "0ms" }} />
        <span className="size-1.5 rounded-full bg-muted-foreground/40 animate-bounce" style={{ animationDelay: "150ms" }} />
        <span className="size-1.5 rounded-full bg-muted-foreground/40 animate-bounce" style={{ animationDelay: "300ms" }} />
      </span>
      <span>Generating response</span>
    </div>
  );
}
