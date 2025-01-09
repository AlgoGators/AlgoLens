"use client";

import "./globals.css";

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <head>
        <meta charSet="UTF-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0" />
        <meta name="description" content="Quantitative trading dashboard" />
        <title>Quant Dashboard</title>
      </head>
      <body className="min-h-screen bg-gray-100 text-gray-900">
        <div className="container mx-auto p-4">{children}</div>
      </body>
    </html>
  );
}
