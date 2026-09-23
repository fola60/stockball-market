import type { Metadata } from "next";
import { headers } from "next/headers";
import { orbitron, plexMono } from "./fonts";
import "./globals.css";

export async function generateMetadata(): Promise<Metadata> {
  const requestHeaders = await headers();
  const host = requestHeaders.get("x-forwarded-host") ?? requestHeaders.get("host") ?? "localhost:3000";
  const protocol = requestHeaders.get("x-forwarded-proto") ?? (host.includes("localhost") ? "http" : "https");
  const origin = `${protocol}://${host}`;

  return {
    title: "Stockball — The Football Market",
    description: "Build a virtual portfolio of Premier League player shares.",
    icons: { icon: "/favicon.svg", shortcut: "/favicon.svg" },
    openGraph: {
      title: "Stockball — The Football Market",
      description: "Build a virtual portfolio of Premier League player shares.",
      images: [{ url: `${origin}/og.png`, width: 1536, height: 1024, alt: "Stockball — The Football Market" }],
    },
    twitter: {
      card: "summary_large_image",
      title: "Stockball — The Football Market",
      description: "Build a virtual portfolio of Premier League player shares.",
      images: [`${origin}/og.png`],
    },
  };
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body
        className={`${orbitron.className} ${orbitron.variable} ${plexMono.variable} antialiased`}
      >
        {children}
      </body>
    </html>
  );
}
