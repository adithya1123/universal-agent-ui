"use client";

import { useState, useCallback, useEffect } from "react";
import { ThemeProvider } from "@/components/theme-provider";
import { Sidebar } from "@/components/sidebar";
import { Chat } from "@/components/chat";
import { RegisterAgentDialog } from "@/components/register-agent-dialog";
import { apiGet, apiDelete, autoTitleThread, renameThread, listAgents, registerAgent, AgentSummary } from "@/lib/api";

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
  const [activeAgentId, setActiveAgentId] = useState(DEFAULT_AGENT_ID);
  const [agents, setAgents] = useState<AgentSummary[]>([]);
  const [showRegisterDialog, setShowRegisterDialog] = useState(false);

  const fetchAgents = useCallback(async () => {
    try {
      const data = await listAgents();
      setAgents(data);
    } catch {
      // Backend not available yet
    }
  }, []);

  useEffect(() => {
    fetchAgents();
  }, [fetchAgents]);

  const fetchSessions = useCallback(async () => {
    if (!activeAgentId) return;
    try {
      const data = await apiGet<{ sessions: Array<{ thread_id: string; title: string; created_at: string }> }>(
        `/api/sessions?agent_id=${activeAgentId}&user_id=${encodeURIComponent(userId)}&limit=50`
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
  }, [userId, activeAgentId]);

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
    if (!activeAgentId) return;
    try {
      await apiDelete(`/api/sessions/${encodeURIComponent(id)}?agent_id=${activeAgentId}`);
      setSessions((prev) => prev.filter((s) => s.id !== id));
      if (activeSessionId === id) {
        setActiveSessionId(undefined);
        setChatKey((k) => k + 1);
      }
    } catch (err) {
      console.error("[page] delete session failed:", err);
    }
  }, [activeSessionId, activeAgentId]);

  const [generatingTitleId, setGeneratingTitleId] = useState<string | null>(null);

  const handleAutoTitle = useCallback(async (threadId: string) => {
    if (!activeAgentId) return;
    setGeneratingTitleId(threadId);
    try {
      const { title } = await autoTitleThread(activeAgentId, threadId);
      setSessions((prev) =>
        prev.map((s) => (s.id === threadId ? { ...s, title } : s)),
      );
    } catch (err) {
      console.error("[page] auto-title failed:", err);
    } finally {
      setGeneratingTitleId(null);
    }
  }, [activeAgentId]);

  const handleRenameSession = useCallback(async (threadId: string, newTitle: string) => {
    if (!activeAgentId) return;
    const trimmed = newTitle.trim();
    if (!trimmed) return;
    try {
      await renameThread(activeAgentId, threadId, trimmed);
      setSessions((prev) =>
        prev.map((s) => (s.id === threadId ? { ...s, title: trimmed } : s)),
      );
    } catch (err) {
      console.error("[page] rename session failed:", err);
    }
  }, [activeAgentId]);

  const handleSelectAgent = useCallback((agentId: string) => {
    setActiveAgentId(agentId);
    setActiveSessionId(undefined);
    setChatKey((k) => k + 1);
  }, []);

  const handleRegisterAgent = useCallback(async (
    name: string, endpointUrl: string, endpointType: string, description?: string,
  ) => {
    const newAgent = await registerAgent(name, endpointUrl, endpointType, description);
    setAgents((prev) => [...prev, newAgent]);
    setActiveAgentId(newAgent.id);
    setActiveSessionId(undefined);
    setChatKey((k) => k + 1);
  }, []);

  return (
    <ThemeProvider>
      <div className="flex h-dvh">
        <Sidebar
          sessions={sessions}
          activeSessionId={activeSessionId}
          onNewChat={handleNewChat}
          onSelectSession={handleSelectSession}
          onDeleteSession={handleDeleteSession}
          onAutoTitle={handleAutoTitle}
          onRenameSession={handleRenameSession}
          generatingTitleId={generatingTitleId}
          collapsed={sidebarCollapsed}
          onToggleCollapse={() => setSidebarCollapsed((c) => !c)}
          userId={userId}
          agentId={activeAgentId}
          agents={agents}
          activeAgentId={activeAgentId}
          onSelectAgent={handleSelectAgent}
          onOpenRegisterAgent={() => setShowRegisterDialog(true)}
        />
        <main className="flex-1 flex flex-col min-w-0">
          <Chat key={`${chatKey}-${activeAgentId}`} agentId={activeAgentId} threadId={activeSessionId} userId={userId} onThreadCreated={fetchSessions} />
        </main>
      </div>
      <RegisterAgentDialog
        open={showRegisterDialog}
        onClose={() => setShowRegisterDialog(false)}
        onRegister={handleRegisterAgent}
      />
    </ThemeProvider>
  );
}
