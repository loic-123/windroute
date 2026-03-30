"use client";

import "./globals.css";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { Navbar } from "@/components/layout/navbar";

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const [queryClient] = useState(() => new QueryClient());

  return (
    <html lang="fr">
      <head>
        <title>WindRoute</title>
        <meta name="description" content="Optimized cycling route generator" />
        <link
          rel="stylesheet"
          href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
          crossOrigin=""
        />
      </head>
      <body className="min-h-screen bg-gray-950 text-gray-100">
        <QueryClientProvider client={queryClient}>
          <Navbar />
          <main className="max-w-7xl mx-auto px-4 py-6">{children}</main>
        </QueryClientProvider>
      </body>
    </html>
  );
}
