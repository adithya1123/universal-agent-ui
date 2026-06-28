"use client";

import { useState, useEffect, useRef } from "react";
import { useAgent, useCopilotKit } from "@copilotkit/react-core/v2";
import { ChatHeader } from "./chat-header";
import { Messages } from "./messages";
import { MultimodalInput } from "./multimodal-input";
import { apiGet } from "@/lib/api";

export function Chat({
  agentId,
  threadId,
  userId,
  onThreadCreated,
}: {
  agentId?: string;
  threadId?: string;
  userId?: string;
  onThreadCreated?: () => void;
}) {
  const [currentThreadId] = useState(() => threadId || crypto.randomUUID());
  const { agent } = useAgent();
  const { copilotkit } = useCopilotKit();
  const historyLoaded = useRef(false);
  const isNewChat = useRef(!threadId);

  useEffect(() => {
    agent.setState({ threadId: currentThreadId });
    if (isNewChat.current) {
      agent.setMessages([]);
    }
  }, [currentThreadId, agent]);

  useEffect(() => {
    console.log("[chat] useEffect:", { threadId, agentId, historyLoaded: historyLoaded.current, currentThreadId });
    if (!threadId || !agentId || historyLoaded.current) return;
    historyLoaded.current = true;

    (async () => {
      try {
        const data = await apiGet<{ messages: Array<{ role: string; content: string }> }>(
          `/api/sessions/${encodeURIComponent(currentThreadId)}?agent_id=${encodeURIComponent(agentId)}`
        );
        console.log("[chat] history loaded:", data.messages.length, "messages",
          data.messages.map((m) => ({ role: m.role, content: (m.content || "").substring(0, 40) })));
        agent.setMessages(
          data.messages.map((m) => ({
            id: crypto.randomUUID(),
            role: m.role as "user" | "assistant",
            content: m.content,
          }))
        );
        console.log("[chat] setMessages done, agent.messages count:", agent.messages.length);
      } catch (err) {
        console.error("[chat] history fetch failed:", err);
      }
    })();
  }, [threadId, agentId, agent, currentThreadId]);

  const messages = (agent.messages as Array<{ role: string; content?: string }>)
    .filter((m) => m.role === "user" || m.role === "assistant")
    .map((m) => ({
      role: m.role as "user" | "assistant",
      content: m.content || "",
    }));

  const isStreaming = agent.isRunning;

  const handleSend = async (text: string) => {
    const isNew = isNewChat.current;
    agent.addMessage({ id: crypto.randomUUID(), role: "user", content: text });
    try {
      await copilotkit.runAgent({
        agent,
        forwardedProps: { userId, agentId },
      });
      if (isNew && onThreadCreated) {
        onThreadCreated();
      }
    } catch (err) {
      console.error("[chat] agent run failed:", err);
      agent.addMessage({
        id: crypto.randomUUID(),
        role: "assistant",
        content: "Sorry, something went wrong. The backend may be unavailable. Please try again.",
      });
    }
  };

  const handleStop = () => {
    agent.abortRun();
  };

  return (
    <div className="flex flex-col h-full">
      <ChatHeader title="Universal Agent" />
      <Messages messages={messages} isStreaming={isStreaming} />
      <MultimodalInput
        onSend={handleSend}
        onStop={handleStop}
        isStreaming={isStreaming}
      />
    </div>
  );
}
