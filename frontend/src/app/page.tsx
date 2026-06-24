"use client";

import { useState, useCallback, useEffect } from "react";
import { ThemeProvider } from "@/components/theme-provider";
import { Sidebar } from "@/components/sidebar";
import { Chat } from "@/components/chat";
import { apiGet, apiDelete } from "@/lib/api";

interface ChatSession {
  id: string;
  title: string;
  date: Date;
}

function getUserId(): string {
  if (typeof window === "undefined") return "anonymous";
  let userId = localStorage.getItem("universal-agent-user-id");
  if (!userId) {
    userId = crypto.randomUUID();
    localStorage.setItem("universal-agent-user-id", userId);
  }
  return userId;
}

const DEFAULT_AGENT_ID = process.env.NEXT_PUBLIC_DEFAULT_AGENT_ID || "";

export default function Home() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string>();
  const [chatKey, setChatKey] = useState(0);
  const [userId] = useState(getUserId);

  const fetchSessions = useCallback(async () => {
    try {
      const data = await apiGet<{ sessions: Array<{ thread_id: string; title: string; created_at: string }> }>(
        `/api/sessions?agent_id=${DEFAULT_AGENT_ID}&user_id=${encodeURIComponent(userId)}&limit=50`
      );
      console.log("[page] sessions loaded:", data.sessions.length, data.sessions.map(s => s.thread_id));
      setSessions(
        data.sessions.map((s) => ({
          id: s.thread_id,
          title: s.title,
          date: new Date(s.created_at),
        }))
      );
    } catch {
      // Backend not available yet — keep empty
    }
  }, [userId]);

  useEffect(() => {
    fetchSessions();
  }, [fetchSessions]);

  const handleNewChat = useCallback(() => {
    setActiveSessionId(undefined);
    setChatKey((k) => k + 1);
  }, []);

  const handleSelectSession = useCallback((id: string) => {
    setActiveSessionId(id);
    setChatKey((k) => k + 1);
  }, []);

  const handleDeleteSession = useCallback(async (id: string) => {
    try {
      await apiDelete(`/api/sessions/${encodeURIComponent(id)}?agent_id=${DEFAULT_AGENT_ID}`);
      setSessions((prev) => prev.filter((s) => s.id !== id));
      if (activeSessionId === id) {
        setActiveSessionId(undefined);
        setChatKey((k) => k + 1);
      }
    } catch (err) {
      console.error("[page] delete session failed:", err);
    }
  }, [activeSessionId]);

  return (
    <ThemeProvider>
      <div className="flex h-dvh">
        <Sidebar
          sessions={sessions}
          activeSessionId={activeSessionId}
          onNewChat={handleNewChat}
          onSelectSession={handleSelectSession}
          onDeleteSession={handleDeleteSession}
          collapsed={sidebarCollapsed}
          onToggleCollapse={() => setSidebarCollapsed((c) => !c)}
        />
        <main className="flex-1 flex flex-col min-w-0">
          <Chat key={chatKey} agentId={DEFAULT_AGENT_ID} threadId={activeSessionId} userId={userId} onThreadCreated={fetchSessions} />
        </main>
      </div>
    </ThemeProvider>
  );
}
