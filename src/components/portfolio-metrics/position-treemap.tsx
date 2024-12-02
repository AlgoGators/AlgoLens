"use client";
import {
  treemap,
  hierarchy,
  ScaleLinear,
  scaleLinear,
  select,
  interpolateRgb,
} from "d3";
import { useEffect, useRef } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { PortfolioData, Position } from "@/types/portfolio";

interface PositionTreemapProps {
  positions: PortfolioData["positions"];
}

export const PositionTreemap = ({ positions }: PositionTreemapProps) => {
  const svgRef = useRef<SVGSVGElement>(null);

  useEffect(() => {
    if (!svgRef.current || positions.length === 0) return;

    // Clear previous content
    const svg = select(svgRef.current);
    svg.selectAll("*").remove();

    // Setup dimensions
    const width = 600;
    const height = 400;
    const margin = { top: 10, right: 10, bottom: 10, left: 10 };

    // Prepare data for treemap
    const data = {
      name: "Portfolio",
      children: positions.map((pos) => ({
        name: pos.symbol,
        value: Math.abs(pos.quantity * pos.currentPrice),
        pnl: pos.pnl,
        position: pos,
      })),
    };

    // Create color scale for PnL
    const colorScale = scaleLinear<string>()
      .domain([
        -Math.max(...positions.map((p) => Math.abs(p.pnl))),
        Math.max(...positions.map((p) => Math.abs(p.pnl))),
      ])
      .range(["#ef4444", "#22c55e"]) // red to green
      .interpolate(interpolateRgb.gamma(2.2));

    // Create treemap layout
    const root = hierarchy(data).sum((d) => (d as any).value || 0);

    const treeLayout = treemap<typeof data>()
      .size([
        width - margin.left - margin.right,
        height - margin.top - margin.bottom,
      ])
      .padding(1);

    treeLayout(root);

    // Create SVG
    svg
      .attr("width", width)
      .attr("height", height)
      .append("g")
      .attr("transform", `translate(${margin.left},${margin.top})`);

    // Add rectangles
    const nodes = svg
      .selectAll("g")
      .data(root.leaves())
      .join("g")
      .attr("transform", (d) => `translate(${d.x0},${d.y0})`);

    nodes
      .append("rect")
      .attr("width", (d) => d.x1 - d.x0)
      .attr("height", (d) => d.y1 - d.y0)
      .attr("fill", (d) => colorScale((d.data as any).pnl))
      .attr("stroke", "#fff")
      .attr("stroke-width", 1);

    // Add text labels
    nodes
      .append("text")
      .attr("x", 5)
      .attr("y", 20)
      .text((d) => `${(d.data as any).name}`)
      .attr("font-size", "12px")
      .attr("fill", "white");

    nodes
      .append("text")
      .attr("x", 5)
      .attr("y", 35)
      .text((d) => `$${(d.data as any).value.toLocaleString()}`)
      .attr("font-size", "10px")
      .attr("fill", "white");
  }, [positions]);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Position Allocation</CardTitle>
      </CardHeader>
      <CardContent>
        <svg ref={svgRef} />
      </CardContent>
    </Card>
  );
};
