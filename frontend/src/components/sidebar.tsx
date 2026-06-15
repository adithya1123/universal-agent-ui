"use client";

import { useState } from "react";
import { useTheme } from "next-themes";
import {
  MessageSquarePlus,
  ChevronLeft,
  ChevronRight,
  Moon,
  Sun,
  Trash2,
} from "lucide-react";
import { cn } from "@/lib/utils";

interface ChatSession {
  id: string;
  title: string;
  date: Date;
}

export function Sidebar({
  sessions,
  activeSessionId,
  onNewChat,
  onSelectSession,
  onDeleteSession,
  collapsed,
  onToggleCollapse,
}: {
  sessions: ChatSession[];
  activeSessionId?: string;
  onNewChat: () => void;
  onSelectSession: (id: string) => void;
  onDeleteSession: (id: string) => void;
  collapsed: boolean;
  onToggleCollapse: () => void;
}) {
  const { theme, setTheme } = useTheme();
  const [hoveredId, setHoveredId] = useState<string | null>(null);

  return (
    <div
      className={cn(
        "flex flex-col h-full bg-sidebar border-r border-sidebar-border transition-all duration-200",
        collapsed ? "w-[52px]" : "w-[260px]",
      )}
    >
      {/* Header */}
      <div className="flex items-center h-11 px-3 border-b border-sidebar-border">
        {!collapsed && (
          <span className="text-base font-semibold text-sidebar-foreground flex-1">
            Chatbot
          </span>
        )}
        <button
          onClick={onToggleCollapse}
          className="p-1 rounded hover:bg-sidebar-accent text-sidebar-foreground/60 hover:text-sidebar-foreground"
        >
          {collapsed ? (
            <ChevronRight className="size-4" />
          ) : (
            <ChevronLeft className="size-4" />
          )}
        </button>
      </div>

      {/* New chat button */}
      <div className="px-2 pt-2">
        <button
          onClick={onNewChat}
          className={cn(
            "flex items-center gap-2 w-full px-3 py-2 rounded-md text-sm text-sidebar-foreground hover:bg-sidebar-accent transition-colors",
            collapsed && "justify-center px-0",
          )}
        >
          <MessageSquarePlus className="size-4 shrink-0" />
          {!collapsed && <span>New chat</span>}
        </button>
      </div>

      {/* Session list */}
      {!collapsed && (
        <div className="flex-1 overflow-y-auto px-2 py-2 space-y-0.5">
          {sessions.length === 0 && (
            <p className="px-3 py-8 text-sm text-muted-foreground text-center">
              No chat history
            </p>
          )}
          {sessions.map((session) => (
            <div
              key={session.id}
              className="group relative"
              onMouseEnter={() => setHoveredId(session.id)}
              onMouseLeave={() => setHoveredId(null)}
            >
              <button
                onClick={() => onSelectSession(session.id)}
                className={cn(
                  "w-full text-left px-3 py-2 rounded-md text-sm truncate transition-colors",
                  activeSessionId === session.id
                    ? "bg-sidebar-accent text-sidebar-accent-foreground"
                    : "text-sidebar-foreground/80 hover:bg-sidebar-accent/50",
                )}
              >
                {session.title}
              </button>
              {hoveredId === session.id && (
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    onDeleteSession(session.id);
                  }}
                  className="absolute right-1 top-1/2 -translate-y-1/2 p-1 rounded text-muted-foreground hover:text-destructive hover:bg-sidebar-accent"
                >
                  <Trash2 className="size-3.5" />
                </button>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Footer */}
      <div className="border-t border-sidebar-border p-2">
        <button
          onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
          className={cn(
            "flex items-center gap-2 w-full px-3 py-2 rounded-md text-sm text-sidebar-foreground hover:bg-sidebar-accent transition-colors",
            collapsed && "justify-center px-0",
          )}
        >
          {theme === "dark" ? (
            <Sun className="size-4 shrink-0" />
          ) : (
            <Moon className="size-4 shrink-0" />
          )}
          {!collapsed && <span>Switch theme</span>}
        </button>
      </div>
    </div>
  );
}
