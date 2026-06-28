"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import {
  Plus,
  Trash2,
  RefreshCw,
  Bookmark,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  listMemories,
  saveMemory,
  deleteMemory,
  MemoryEntry,
} from "@/lib/api";

function formatRelativeTime(iso: string | undefined): string {
  if (!iso) return "";
  const then = new Date(iso);
  const now = new Date();
  const diffMs = now.getTime() - then.getTime();
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 1) return "Just now";
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDays = Math.floor(diffHr / 24);
  if (diffDays < 30) return `${diffDays}d ago`;
  const diffMonths = Math.floor(diffDays / 30);
  return `${diffMonths}mo ago`;
}

const CATEGORY_COLORS: Record<string, string> = {
  preference: "bg-blue-500/10 text-blue-600 dark:text-blue-400",
  project: "bg-green-500/10 text-green-600 dark:text-green-400",
  background: "bg-purple-500/10 text-purple-600 dark:text-purple-400",
  constraint: "bg-amber-500/10 text-amber-600 dark:text-amber-400",
};

export function MemoryPanel({
  agentId,
  userId,
  collapsed,
}: {
  agentId: string;
  userId: string;
  collapsed: boolean;
}) {
  const [memories, setMemories] = useState<MemoryEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showAdd, setShowAdd] = useState(false);
  const [newKey, setNewKey] = useState("");
  const [newValue, setNewValue] = useState("");
  const [newCategory, setNewCategory] = useState("preference");

  const sortedMemories = useMemo(() => {
    return [...memories].sort((a, b) => {
      const aScore = (a.access_count ?? 0) * 0.3;
      const bScore = (b.access_count ?? 0) * 0.3;
      return bScore - aScore;
    });
  }, [memories]);

  const fetchMemories = useCallback(async () => {
    if (!agentId || !userId) return;
    setLoading(true);
    setError(null);
    try {
      const data = await listMemories(agentId, userId);
      setMemories(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load memories");
    } finally {
      setLoading(false);
    }
  }, [agentId, userId]);

  useEffect(() => {
    if (!collapsed) fetchMemories();
  }, [collapsed, fetchMemories]);

  const handleAdd = async () => {
    if (!newKey.trim() || !newValue.trim()) return;
    try {
      await saveMemory(agentId, userId, newKey.trim(), {
        value: newValue.trim(),
        category: newCategory,
      });
      setNewKey("");
      setNewValue("");
      setNewCategory("preference");
      setShowAdd(false);
      await fetchMemories();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save memory");
    }
  };

  const handleDelete = async (key: string) => {
    try {
      await deleteMemory(agentId, userId, key);
      setMemories((prev) => prev.filter((m) => m.key !== key));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete memory");
    }
  };

  if (collapsed) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <Bookmark className="size-5 text-sidebar-foreground/40" />
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      {/* Header row */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-sidebar-border">
        <span className="text-sm font-medium text-sidebar-foreground">
          Memories ({memories.length})
        </span>
        <div className="flex items-center gap-1">
          <button
            onClick={fetchMemories}
            className="p-1 rounded hover:bg-sidebar-accent text-sidebar-foreground/60 hover:text-sidebar-foreground"
            title="Refresh"
          >
            <RefreshCw className={cn("size-3.5", loading && "animate-spin")} />
          </button>
          <button
            onClick={() => setShowAdd(!showAdd)}
            className="p-1 rounded hover:bg-sidebar-accent text-sidebar-foreground/60 hover:text-sidebar-foreground"
            title="Add memory"
          >
            {showAdd ? <X className="size-3.5" /> : <Plus className="size-3.5" />}
          </button>
        </div>
      </div>

      {/* Add form */}
      {showAdd && (
        <div className="px-3 py-2 border-b border-sidebar-border space-y-2 bg-sidebar-accent/30">
          <input
            placeholder="Key (e.g., preferred_language)"
            value={newKey}
            onChange={(e) => setNewKey(e.target.value)}
            className="w-full px-2 py-1.5 text-xs rounded border border-sidebar-border bg-background text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
          <textarea
            placeholder="Value (what to remember)"
            value={newValue}
            onChange={(e) => setNewValue(e.target.value)}
            rows={2}
            className="w-full px-2 py-1.5 text-xs rounded border border-sidebar-border bg-background text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-blue-500 resize-none"
          />
          <div className="flex items-center gap-2">
            <select
              value={newCategory}
              onChange={(e) => setNewCategory(e.target.value)}
              className="flex-1 px-2 py-1.5 text-xs rounded border border-sidebar-border bg-background text-foreground focus:outline-none focus:ring-1 focus:ring-blue-500"
            >
              <option value="preference">Preference</option>
              <option value="project">Project</option>
              <option value="background">Background</option>
              <option value="constraint">Constraint</option>
              <option value="other">Other</option>
            </select>
            <button
              onClick={handleAdd}
              disabled={!newKey.trim() || !newValue.trim()}
              className="px-3 py-1.5 text-xs rounded bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              Save
            </button>
          </div>
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="px-3 py-1.5 text-xs text-red-500 bg-red-500/10 border-b border-sidebar-border">
          {error}
        </div>
      )}

      {/* Memory list */}
      <div className="flex-1 overflow-y-auto px-2 py-2 space-y-1.5">
        {loading && memories.length === 0 && (
          <p className="px-3 py-8 text-xs text-muted-foreground text-center">
            Loading...
          </p>
        )}
        {!loading && memories.length === 0 && (
          <p className="px-3 py-8 text-xs text-muted-foreground text-center">
            No memories saved yet.
            <br />
            <button
              onClick={() => setShowAdd(true)}
              className="text-blue-500 hover:underline mt-1"
            >
              Add one
            </button>
          </p>
        )}
        {sortedMemories.map((mem) => (
          <div
            key={mem.key}
            className="group relative p-2.5 rounded-md text-xs bg-sidebar-accent/30 hover:bg-sidebar-accent/50 transition-colors"
          >
            <div className="flex items-start justify-between gap-1">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-1.5 flex-wrap mb-1">
                  <span className="font-medium text-sidebar-foreground truncate max-w-[140px]">
                    {mem.key}
                  </span>
                  {mem.category && (
                    <span
                      className={cn(
                        "px-1.5 py-0.5 rounded text-[10px] font-medium leading-none",
                        CATEGORY_COLORS[mem.category] ||
                          "bg-neutral-500/10 text-neutral-600 dark:text-neutral-400",
                      )}
                    >
                      {mem.category}
                    </span>
                  )}
                </div>
                <p className="text-sidebar-foreground/70 leading-relaxed line-clamp-3">
                  {mem.value}
                </p>
                {mem.updated_at && (
                  <p className="text-[10px] text-sidebar-foreground/40 mt-1">
                    Updated {formatRelativeTime(mem.updated_at)}
                  </p>
                )}
              </div>
              <button
                onClick={() => handleDelete(mem.key)}
                className="shrink-0 p-1 rounded text-muted-foreground/40 hover:text-red-500 hover:bg-red-500/10 opacity-0 group-hover:opacity-100 transition-all"
                title="Delete memory"
              >
                <Trash2 className="size-3" />
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
