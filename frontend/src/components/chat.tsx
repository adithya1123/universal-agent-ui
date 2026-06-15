"use client";

import { useAgent } from "@copilotkit/react-core/v2";
import { ChatHeader } from "./chat-header";
import { Messages } from "./messages";
import { MultimodalInput } from "./multimodal-input";

export function Chat({ agentId }: { agentId?: string }) {
  const { agent } = useAgent({ agentId });

  const messages = (agent.messages as Array<{ role: string; content?: string }>)
    .filter((m) => m.role === "user" || m.role === "assistant")
    .map((m) => ({
      role: m.role as "user" | "assistant",
      content: m.content || "",
    }));

  const isStreaming = agent.isRunning;

  const handleSend = async (text: string) => {
    (agent as any).addMessage({ role: "user", content: text });
    await agent.runAgent();
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
