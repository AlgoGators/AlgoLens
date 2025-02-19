"use client";

import { Line } from "react-chartjs-2";
import { Chart as ChartJS, CategoryScale, LinearScale, PointElement, LineElement, Title, Tooltip, Legend, Zoom } from "chart.js";
import zoomPlugin from "chartjs-plugin-zoom";

// Register necessary components and plugins
ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Title, Tooltip, Legend, zoomPlugin);

interface ChartProps {
  data: any; // Chart.js-compatible data object
  options?: any; // Chart.js options
  title: string; // Chart title
}

const Chart: React.FC<ChartProps> = ({ data, options, title }) => {
  return (
    <div className="bg-white shadow rounded-lg p-6 mb-8">
      <h2 className="text-xl font-bold mb-4">{title}</h2>
      <Line
        data={data}
        options={{
          responsive: true,
          plugins: {
            legend: {
              display: true,
              position: "top",
            },
            title: {
              display: true,
              text: title,
              color: "#333333",
              font: {
                size: 16,
                weight: "bold",
              },
            },
            zoom: {
              zoom: {
                wheel: { enabled: true },
                pinch: { enabled: true },
                mode: "x",
              },
              pan: {
                enabled: true,
                mode: "x",
              },
            },
            tooltip: {
              enabled: true,
            },
          },
          scales: {
            x: {
              title: {
                display: true,
                text: "Date",
                color: "#333333",
                font: { size: 14, weight: "bold" },
              },
            },
            y: {
              title: {
                display: true,
                text: "Value",
                color: "#333333",
                font: { size: 14, weight: "bold" },
              },
            },
          },
          ...options, // Merge custom options
        }}
      />
    </div>
  );
};

export default Chart;
