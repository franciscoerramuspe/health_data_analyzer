import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Health Chat",
  description: "Ask questions about your own Whoop data.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          fontFamily:
            "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
          background: "#0b0b0c",
          color: "#e5e5e5",
        }}
      >
        {children}
      </body>
    </html>
  );
}
