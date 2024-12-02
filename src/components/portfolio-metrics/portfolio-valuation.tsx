import { Label } from "@/components/ui/label";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
} from "@/components/ui/card";

import { TrendingUp, TrendingDown } from "lucide-react";
import { PortfolioData, Position } from "@/types/portfolio";

interface PortfolioValuationProps {
  value: PortfolioData["portfolioValue"];
  totalReturn: PortfolioData["totalReturn"];
}

const DECIMAL_PLACES = 2;
const CURRENCY = "USD";

const formatCurrency = (value: number) =>
  value.toLocaleString("en-US", {
    style: "currency",
    currency: CURRENCY,
    maximumFractionDigits: DECIMAL_PLACES,
  });

export const PortfolioValuation = ({
  value = 0,
  totalReturn = 0,
}: PortfolioValuationProps) => {
  const isPositve = totalReturn >= 0;

  return (
    <Card className="w-full max-w-lg">
      <CardHeader>
        <h2 className="text-2xl font-semibold">Portfolio Metrics</h2>
        <CardDescription>
          View your portfolio metrics and performance
        </CardDescription>
      </CardHeader>
      <CardContent className="pt-6">
        <div className="flex justify-between items-center">
          <div className="space-y-1.5 ">
            <Label htmlFor="total-invested">Total Invested</Label>
            <p className="text-lg font-semibold">{formatCurrency(value)}</p>
          </div>

          <div className="text-right space-y-1">
            <p className="text-sm text-muted-foreground">Total Return</p>
            <div
              className={`flex items-center text-2xl font-bold ${isPositve ? "text-green-600" : "text-red-500"}`}
            >
              {isPositve && "+"}
              {totalReturn * 100}%{" "}
              {isPositve ? <TrendingUp /> : <TrendingDown />}
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
};
