"use client";

import { useState, useEffect, useRef } from "react";
import { useTheme } from "next-themes";
import {
  MessageSquarePlus,
  ChevronLeft,
  ChevronRight,
  Moon,
  Sun,
  Trash2,
  Bookmark,
  MessageSquare,
  Sparkles,
  Loader2,
  Pencil,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { MemoryPanel } from "./memory-panel";

interface ChatSession {
  id: string;
  title: string;
  date: Date;
}

type Tab = "chats" | "memories";

export function Sidebar({
  sessions,
  activeSessionId,
  onNewChat,
  onSelectSession,
  onDeleteSession,
  onAutoTitle,
  onRenameSession,
  generatingTitleId,
  collapsed,
  onToggleCollapse,
  userId,
  agentId,
}: {
  sessions: ChatSession[];
  activeSessionId?: string;
  onNewChat: () => void;
  onSelectSession: (id: string) => void;
  onDeleteSession: (id: string) => void;
  onAutoTitle: (id: string) => void;
  onRenameSession: (id: string, title: string) => void;
  generatingTitleId: string | null;
  collapsed: boolean;
  onToggleCollapse: () => void;
  userId: string;
  agentId: string;
}) {
  const { theme, setTheme } = useTheme();
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [mounted, setMounted] = useState(false);
  const [tab, setTab] = useState<Tab>("chats");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");
  const editInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editingId && editInputRef.current) {
      editInputRef.current.focus();
      editInputRef.current.select();
    }
  }, [editingId]);
  useEffect(() => setMounted(true), []);

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
            Agent UI
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

      {/* Tab switcher */}
      {!collapsed && (
        <div className="flex border-b border-sidebar-border">
          <button
            onClick={() => setTab("chats")}
            className={cn(
              "flex-1 flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-medium transition-colors",
              tab === "chats"
                ? "text-sidebar-foreground border-b-2 border-blue-500"
                : "text-sidebar-foreground/50 hover:text-sidebar-foreground/80",
            )}
          >
            <MessageSquare className="size-3.5" />
            Chats
          </button>
          <button
            onClick={() => setTab("memories")}
            className={cn(
              "flex-1 flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-medium transition-colors",
              tab === "memories"
                ? "text-sidebar-foreground border-b-2 border-blue-500"
                : "text-sidebar-foreground/50 hover:text-sidebar-foreground/80",
            )}
          >
            <Bookmark className="size-3.5" />
            Memories
          </button>
        </div>
      )}

      {/* New chat button (chats tab only) */}
      {tab === "chats" && !collapsed && (
        <div className="px-2 pt-2">
          <button
            onClick={onNewChat}
            className={cn(
              "flex items-center gap-2 w-full px-3 py-2 rounded-md text-sm text-sidebar-foreground hover:bg-sidebar-accent transition-colors",
            )}
          >
            <MessageSquarePlus className="size-4 shrink-0" />
            <span>New chat</span>
          </button>
        </div>
      )}

      {/* Chats tab: session list */}
      {tab === "chats" && !collapsed && (
        <div className="flex-1 overflow-y-auto px-2 py-2 space-y-0.5">
          {sessions.length === 0 && (
            <p className="px-3 py-8 text-sm text-muted-foreground text-center">
              No chat history
            </p>
          )}
          {sessions.map((session) => {
            const isEditing = editingId === session.id;
            const isGenerating = generatingTitleId === session.id;

            const startEdit = () => {
              setEditingId(session.id);
              setEditValue(session.title);
            };

            const commitEdit = () => {
              setEditingId(null);
              if (editValue.trim() && editValue.trim() !== session.title) {
                onRenameSession(session.id, editValue.trim());
              }
            };

            const cancelEdit = () => {
              setEditingId(null);
              setEditValue("");
            };

            return (
              <div
                key={session.id}
                className="group relative"
                onMouseEnter={() => setHoveredId(session.id)}
                onMouseLeave={() => {
                  setHoveredId(null);
                  if (isEditing) commitEdit();
                }}
              >
                {isEditing ? (
                  <input
                    ref={editInputRef}
                    value={editValue}
                    onChange={(e) => setEditValue(e.target.value)}
                    onClick={(e) => e.stopPropagation()}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        commitEdit();
                      } else if (e.key === "Escape") {
                        e.preventDefault();
                        cancelEdit();
                      }
                    }}
                    className="w-full px-3 py-2 rounded-md text-sm bg-background border border-blue-500 outline-none"
                  />
                ) : (
                  <button
                    onClick={() => onSelectSession(session.id)}
                    onDoubleClick={(e) => {
                      e.stopPropagation();
                      startEdit();
                    }}
                    className={cn(
                      "w-full text-left px-3 py-2 rounded-md text-sm truncate transition-colors",
                      activeSessionId === session.id
                        ? "bg-sidebar-accent text-sidebar-accent-foreground"
                        : "text-sidebar-foreground/80 hover:bg-sidebar-accent/50",
                    )}
                  >
                    {session.title}
                  </button>
                )}
                {!isEditing && hoveredId === session.id && (
                  <div className="absolute right-1 top-1/2 -translate-y-1/2 flex items-center gap-0.5">
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        onAutoTitle(session.id);
                      }}
                      disabled={isGenerating}
                      className="p-1 rounded text-muted-foreground hover:text-blue-500 hover:bg-sidebar-accent disabled:opacity-50"
                      title="Auto-generate title"
                    >
                      {isGenerating ? (
                        <Loader2 className="size-3.5 animate-spin" />
                      ) : (
                        <Sparkles className="size-3.5" />
                      )}
                    </button>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        startEdit();
                      }}
                      className="p-1 rounded text-muted-foreground hover:text-sidebar-foreground hover:bg-sidebar-accent"
                      title="Rename"
                    >
                      <Pencil className="size-3.5" />
                    </button>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        onDeleteSession(session.id);
                      }}
                      className="p-1 rounded text-muted-foreground hover:text-destructive hover:bg-sidebar-accent"
                      title="Delete"
                    >
                      <Trash2 className="size-3.5" />
                    </button>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Memories tab */}
      {tab === "memories" && (
        <MemoryPanel
          agentId={agentId}
          userId={userId}
          collapsed={collapsed}
        />
      )}

      {/* Collapsed: show indicator */}
      {collapsed && (
        <div className="flex-1 flex items-center justify-center">
          {tab === "memories" ? (
            <Bookmark className="size-5 text-sidebar-foreground/40" />
          ) : (
            <MessageSquare className="size-5 text-sidebar-foreground/40" />
          )}
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
          {mounted && theme === "dark" ? (
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
