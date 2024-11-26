import { Label } from "@/components/ui/label";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export const PortfolioMetrics = () => {
  const portfolioInvested = 10000;
  const totalReturn = 0.2;
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
            <p className="text-lg font-semibold">
              ${portfolioInvested.toLocaleString("en-US")}
            </p>
          </div>

          <div className="text-right space-y-1">
            <p className="text-sm text-muted-foreground">Total Return</p>
            <div
              className={`flex items-center text-2xl font-bold ${isPositve ? "text-green-600" : "text-red-500"}`}
            >
              {isPositve && "+"}
              {totalReturn * 100}%{" "}
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
};
