"use client";

import { useState } from "react";
import { Menubar, MenubarMenu, MenubarTrigger } from "@/components/ui/menubar";
import Link from "next/link";
import Image from "next/image";

export default function GlassFactory() {
  const [pythonCode, setPythonCode] = useState("");
  const [response, setResponse] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmitting(true);
    setResponse("");
    try {
      const res = await fetch("http://localhost:5000/api/glassfactory", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ code: pythonCode }),
      });
      const data = await res.json();
      setResponse(JSON.stringify(data, null, 2));
    } catch (err: any) {
      setResponse("Error: " + err.message);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="flex flex-col h-screen">
      {/* Header */}
      <Menubar className="h-20 px-4 bg-background shadow-sm">
        <MenubarMenu className="flex items-center space-x-4">
          <MenubarTrigger asChild>
            <Link href="/">
              <Image
                src="/images/AlgoLogo.png"
                alt="AlgoLogo"
                width={60}
                height={60}
                loading="eager"
              />
            </Link>
          </MenubarTrigger>
          <span className="text-3xl font-bold">Glass Factory</span>
        </MenubarMenu>
      </Menubar>

      {/* Main Content */}
      <div className="flex flex-grow">
        {/* Left Pane: Python Code Editor */}
        <div className="w-1/2 p-4 border-r border-gray-300 flex flex-col">
          <h1 className="text-2xl font-bold mb-4">Python Code</h1>
          <form onSubmit={handleSubmit} className="flex flex-col flex-grow">
            <textarea
              className="flex-grow w-full p-2 border border-gray-300 rounded resize-none"
              placeholder="Enter Python code here..."
              value={pythonCode}
              onChange={(e) => setPythonCode(e.target.value)}
            />
            <button
              type="submit"
              className="mt-4 px-4 py-2 bg-blue-600 text-white rounded disabled:opacity-50"
              disabled={isSubmitting}
            >
              {isSubmitting ? "Running..." : "Run Code"}
            </button>
          </form>
        </div>
        {/* Right Pane: Console Output */}
        <div className="w-1/2 p-4 flex flex-col">
          <h1 className="text-2xl font-bold mb-4">Console Output</h1>
          <div className="flex-grow p-2 border border-gray-300 rounded bg-gray-100 overflow-auto whitespace-pre-wrap">
            {response}
          </div>
        </div>
      </div>
    </div>
  );
}
