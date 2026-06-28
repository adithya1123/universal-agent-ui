"use client";

import dynamic from "next/dynamic";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

const Plot = dynamic(() => import("react-plotly.js"), { ssr: false });

interface MessageProps {
  role: "user" | "assistant";
  content: string;
  isLoading?: boolean;
}

type ContentBlock =
  | { type: "text"; content: string }
  | { type: "plotly"; spec: Record<string, unknown> }
  | { type: "plotly-loading" };

const PLOTLY_BLOCK_RE = /```plotly\n([\s\S]*?)```/g;

function parseContent(content: string): ContentBlock[] {
  const blocks: ContentBlock[] = [];
  let lastIdx = 0;
  let match: RegExpExecArray | null;

  while ((match = PLOTLY_BLOCK_RE.exec(content)) !== null) {
    if (match.index > lastIdx) {
      blocks.push({ type: "text", content: content.slice(lastIdx, match.index) });
    }
    try {
      const spec = JSON.parse(match[1]);
      blocks.push({ type: "plotly", spec });
    } catch {
      blocks.push({ type: "text", content: match[0] });
    }
    lastIdx = match.index + match[0].length;
  }

  const remainder = content.slice(lastIdx);
  if (remainder) {
    const unclosed = remainder.match(/```plotly\n([\s\S]*)$/);
    if (unclosed && unclosed.index !== undefined) {
      if (unclosed.index > 0) {
        blocks.push({ type: "text", content: remainder.slice(0, unclosed.index) });
      }
      blocks.push({ type: "plotly-loading" });
    } else {
      blocks.push({ type: "text", content: remainder });
    }
  }

  return blocks;
}

function PlotlyChart({ spec }: { spec: Record<string, unknown> }) {
  const plotly = (spec.plotly_spec as Record<string, unknown> | undefined) ?? spec;
  const data = plotly.data as unknown[] | undefined;
  const layout = (plotly.layout as Record<string, unknown> | undefined) ?? {};
  const config = (plotly.config as Record<string, unknown> | undefined) ?? {};

  if (!data || !Array.isArray(data) || data.length === 0) {
    return null;
  }

  return (
    <div className="my-4 overflow-x-auto">
      <Plot
        data={data}
        layout={{ ...layout, autosize: true }}
        config={{ ...config, responsive: true, displaylogo: false }}
        style={{ width: "100%", height: 400 }}
        useResizeHandler
      />
    </div>
  );
}

function MarkdownContent({ content }: { content: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
        ul: ({ children }) => <ul className="list-disc pl-5 mb-2 space-y-1">{children}</ul>,
        ol: ({ children }) => <ol className="list-decimal pl-5 mb-2 space-y-1">{children}</ol>,
        li: ({ children }) => <li>{children}</li>,
        h1: ({ children }) => <h1 className="text-lg font-semibold mb-2 mt-4 first:mt-0">{children}</h1>,
        h2: ({ children }) => <h2 className="text-base font-semibold mb-2 mt-3 first:mt-0">{children}</h2>,
        h3: ({ children }) => <h3 className="text-sm font-semibold mb-1 mt-3 first:mt-0">{children}</h3>,
        code: ({ className, children, ...props }) => {
          const isInline = !className;
          if (isInline) {
            return (
              <code className="bg-muted px-1 py-0.5 rounded text-xs font-mono" {...props}>
                {children}
              </code>
            );
          }
          return (
            <pre className="bg-muted p-3 rounded-md mb-3 overflow-x-auto text-xs font-mono">
              <code className={className} {...props}>
                {children}
              </code>
            </pre>
          );
        },
        table: ({ children }) => (
          <div className="overflow-x-auto mb-3">
            <table className="min-w-full border-collapse border border-border text-xs">{children}</table>
          </div>
        ),
        thead: ({ children }) => <thead className="bg-muted">{children}</thead>,
        th: ({ children }) => <th className="border border-border px-3 py-1.5 text-left font-medium">{children}</th>,
        td: ({ children }) => <td className="border border-border px-3 py-1.5">{children}</td>,
        a: ({ href, children }) => (
          <a href={href} className="text-primary underline underline-offset-2" target="_blank" rel="noopener noreferrer">
            {children}
          </a>
        ),
        strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
        hr: () => <hr className="my-3 border-border" />,
      }}
    >
      {content}
    </ReactMarkdown>
  );
}

export function Message({ role, content, isLoading }: MessageProps) {
  if (role === "user") {
    return (
      <div className="flex justify-end mb-4">
        <div className="max-w-[70%] bg-secondary text-secondary-foreground rounded-2xl px-4 py-2.5 text-sm leading-relaxed whitespace-pre-wrap">
          {content}
        </div>
      </div>
    );
  }

  return (
    <div className="flex mb-4">
      <div className="max-w-full px-0 py-0 text-sm leading-relaxed">
        {isLoading && !content ? (
          <span className="inline-block bg-ai-gradient rounded-md w-24 h-4 animate-shimmer-text bg-[length:200%_100%]" />
        ) : (
          <MessageContent content={content} />
        )}
      </div>
    </div>
  );
}

function MessageContent({ content }: { content: string }) {
  const blocks = parseContent(content);
  return blocks.map((block, i) => {
    if (block.type === "text") {
      return <MarkdownContent key={i} content={block.content} />;
    }
    if (block.type === "plotly") {
      return <PlotlyChart key={i} spec={block.spec} />;
    }
    return (
      <div key={i} className="my-4 p-4 border rounded-md animate-pulse bg-muted">
        <div className="h-64 bg-muted-foreground/10 rounded" />
      </div>
    );
  });
}

export function AwaitingResponse() {
  return (
    <div className="flex items-center gap-3 py-4 text-sm text-muted-foreground">
      <span className="flex gap-1">
        <span className="size-1.5 rounded-full bg-muted-foreground/40 animate-bounce" style={{ animationDelay: "0ms" }} />
        <span className="size-1.5 rounded-full bg-muted-foreground/40 animate-bounce" style={{ animationDelay: "150ms" }} />
        <span className="size-1.5 rounded-full bg-muted-foreground/40 animate-bounce" style={{ animationDelay: "300ms" }} />
      </span>
      <span>Generating response</span>
    </div>
  );
}
