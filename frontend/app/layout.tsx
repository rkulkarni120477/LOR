import type { Metadata } from "next";
import type { ReactNode } from "react";

import { Nav } from "@/components/Nav";

import "./globals.css";

export const metadata: Metadata = {
  title: "ELOR | Enterprise Learning Object Repository",
  description: "Search, contribute, review, and report on enterprise learning objects.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" data-scroll-behavior="smooth">
      <body className="min-h-screen antialiased">
        <Nav>{children}</Nav>
      </body>
    </html>
  );
}
