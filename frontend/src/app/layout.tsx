"use client";
import "./globals.css";
import localFont from "next/font/local";
import { AuthContextProvider } from "@/context/AuthContext";
import Navbar from "@/components/navbar/navbar";
import { ForcePasswordChange } from "@/components/ForcePasswordChange";

const aileron = localFont({
  src: [
    { path: "/fonts/Aileron-Regular.otf", weight: "400" },
    { path: "/fonts/Aileron-Bold.otf", weight: "700" },
  ],
  display: "swap",
  variable: "--font-aileron",
});

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={aileron.variable}>
      <head>
        <meta charSet="UTF-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0" />
        <meta name="description" content="AlgoLens" />
        <title>AlgoLens</title>
      </head>
      <body className="min-h-screen bg-gray-100 text-gray-900">
        <AuthContextProvider>
          <ForcePasswordChange />
          <div className="container mx-auto p-4 pt-20">{children}</div>
          <Navbar />
        </AuthContextProvider>
      </body>
    </html>
  );
}
