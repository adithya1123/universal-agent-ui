"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface MessageProps {
  role: "user" | "assistant";
  content: string;
  isLoading?: boolean;
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
          <MarkdownContent content={content} />
        )}
      </div>
    </div>
  );
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
