import type { Metadata } from "next";
import { CopilotKit } from "@copilotkit/react-core/v2";
import "./globals.css";

export const metadata: Metadata = {
  title: "Universal Agent UI",
  description: "Chat with any AI agent through a unified interface",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning className="h-full">
      <body className="h-full overflow-hidden">
        <CopilotKit runtimeUrl="/api/copilotkit" useSingleEndpoint>
          {children}
        </CopilotKit>
      </body>
    </html>
  );
}
