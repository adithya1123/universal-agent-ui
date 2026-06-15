"use client";

import { MessageSquarePlus } from "lucide-react";

export function ChatHeader({
  title,
  isEphemeral,
  onNewChat,
}: {
  title: string;
  isEphemeral?: boolean;
  onNewChat?: () => void;
}) {
  return (
    <header className="sticky top-0 z-10 h-[60px] border-b border-border bg-background/95 backdrop-blur-sm">
      <div className="flex items-center h-full px-6">
        <h4 className="text-base font-medium truncate flex-1">{title}</h4>
        <div className="flex items-center gap-2 ml-auto">
          {isEphemeral && (
            <span className="text-xs px-2 py-0.5 rounded-full bg-warning/10 text-warning border border-warning/20">
              Ephemeral
            </span>
          )}
          {onNewChat && (
            <button
              onClick={onNewChat}
              className="flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-md bg-primary text-primary-foreground hover:bg-primary/90 transition-colors"
            >
              <MessageSquarePlus className="size-4" />
              <span className="hidden sm:inline">New Chat</span>
            </button>
          )}
        </div>
      </div>
    </header>
  );
}
