"use client";

import { useState, useCallback } from "react";
import { ThemeProvider } from "@/components/theme-provider";
import { Sidebar } from "@/components/sidebar";
import { Chat } from "@/components/chat";

interface ChatSession {
  id: string;
  title: string;
  date: Date;
}

export default function Home() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [sessions] = useState<ChatSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string>();
  const [chatKey, setChatKey] = useState(0);

  const handleNewChat = useCallback(() => {
    setActiveSessionId(undefined);
    setChatKey((k) => k + 1);
  }, []);

  const handleSelectSession = useCallback((id: string) => {
    setActiveSessionId(id);
  }, []);

  const handleDeleteSession = useCallback((id: string) => {
    console.log("Delete session", id);
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
          collapsed={sidebarCollapsed}
          onToggleCollapse={() => setSidebarCollapsed((c) => !c)}
        />
        <main className="flex-1 flex flex-col min-w-0">
          <Chat key={chatKey} />
        </main>
      </div>
    </ThemeProvider>
  );
}
