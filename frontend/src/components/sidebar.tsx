"use client";

import { useState, useEffect, useRef } from "react";
import { useTheme } from "next-themes";
import {
  MessageSquarePlus,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  Moon,
  Sun,
  Trash2,
  Bookmark,
  MessageSquare,
  Sparkles,
  Loader2,
  Pencil,
  Bot,
  Plus,
  Check,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { MemoryPanel } from "./memory-panel";
import type { AgentSummary } from "@/lib/api";

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
  agents,
  activeAgentId,
  onSelectAgent,
  onOpenRegisterAgent,
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
  agents: AgentSummary[];
  activeAgentId: string;
  onSelectAgent: (id: string) => void;
  onOpenRegisterAgent: () => void;
}) {
  const { theme, setTheme } = useTheme();
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [mounted, setMounted] = useState(false);
  const [tab, setTab] = useState<Tab>("chats");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");
  const editInputRef = useRef<HTMLInputElement>(null);
  const [showAgentDropdown, setShowAgentDropdown] = useState(false);
  const agentDropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (editingId && editInputRef.current) {
      editInputRef.current.focus();
      editInputRef.current.select();
    }
  }, [editingId]);
  useEffect(() => setMounted(true), []);

  useEffect(() => {
    if (!showAgentDropdown) return;
    const handleClickOutside = (e: MouseEvent) => {
      if (agentDropdownRef.current && !agentDropdownRef.current.contains(e.target as Node)) {
        setShowAgentDropdown(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [showAgentDropdown]);

  const currentAgent = agents.find((a) => a.id === activeAgentId);

  return (
    <div
      className={cn(
        "flex flex-col h-full bg-sidebar border-r border-sidebar-border transition-all duration-200",
        collapsed ? "w-[52px]" : "w-[260px]",
      )}
    >
      {/* Header with agent selector */}
      <div className="flex items-center h-11 px-3 border-b border-sidebar-border gap-1">
        {!collapsed && (
          <div ref={agentDropdownRef} className="relative flex-1 min-w-0">
            <button
              onClick={() => setShowAgentDropdown(!showAgentDropdown)}
              className="flex items-center gap-1.5 w-full text-left text-sm font-semibold text-sidebar-foreground hover:text-blue-500 transition-colors truncate pr-1"
            >
              <Bot className="size-4 shrink-0" />
              <span className="truncate flex-1">{currentAgent?.name || agentId || "Select agent"}</span>
              <ChevronDown className={cn("size-3.5 shrink-0 transition-transform", showAgentDropdown && "rotate-180")} />
            </button>
            {showAgentDropdown && (
              <div className="absolute top-full left-0 right-0 mt-1 bg-sidebar border border-sidebar-border rounded-md shadow-xl z-50 py-1 max-h-60 overflow-y-auto">
                {agents.length === 0 && (
                  <p className="px-3 py-2 text-xs text-sidebar-foreground/50">No agents registered</p>
                )}
                {agents.map((a) => (
                  <button
                    key={a.id}
                    onClick={() => {
                      onSelectAgent(a.id);
                      setShowAgentDropdown(false);
                    }}
                    className={cn(
                      "flex items-center gap-2 w-full text-left px-3 py-1.5 text-sm transition-colors",
                      a.id === activeAgentId
                        ? "bg-sidebar-accent text-sidebar-accent-foreground"
                        : "text-sidebar-foreground hover:bg-sidebar-accent/60",
                    )}
                  >
                    <span className="truncate flex-1">{a.name}</span>
                    {a.id === activeAgentId && <Check className="size-3.5 shrink-0 text-blue-500" />}
                  </button>
                ))}
                <div className="border-t border-sidebar-border my-1" />
                <button
                  onClick={() => {
                    setShowAgentDropdown(false);
                    onOpenRegisterAgent();
                  }}
                  className="flex items-center gap-2 w-full text-left px-3 py-1.5 text-sm text-blue-500 hover:bg-sidebar-accent/60 transition-colors"
                >
                  <Plus className="size-3.5 shrink-0" />
                  <span>Register new agent</span>
                </button>
              </div>
            )}
          </div>
        )}
        <button
          onClick={onToggleCollapse}
          className="p-1 rounded hover:bg-sidebar-accent text-sidebar-foreground/60 hover:text-sidebar-foreground shrink-0"
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
