import { NextResponse } from "next/server";

export async function GET() {
  const data = [
    {
      id: "1",
      symbol: "ES",
      quantity: 100,
      entryPrice: 3000.0,
      currentPrice: 3010.0,
      pnl: 1000.0,
      returnPercent: 0.2,
    },
    {
      id: "2",
      symbol: "CL",
      quantity: 100,
      entryPrice: 3000.0,
      currentPrice: 3010.0,
      pnl: 1000.0,
      returnPercent: 0.2,
    },
  ];

  return NextResponse.json(data);
}
