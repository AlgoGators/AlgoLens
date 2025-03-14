import Chart from "../Chart";

export default function ChartDisplay({ chartData, chartTitle, errorMessage }) {
  return (
    <div className="flex-1 flex flex-col">
      <h2 className="text-2xl font-bold mb-4">Chart Preview</h2>
      <div className="flex-grow border border-gray-300 rounded p-4 flex flex-col items-center justify-center">
        {errorMessage ? (
          <div className="text-red-500 p-4 bg-red-50 rounded w-full">
            <h3 className="font-bold mb-2">Error:</h3>
            <pre className="whitespace-pre-wrap">{errorMessage}</pre>
          </div>
        ) : chartData ? (
          <div className="w-full h-full flex flex-col">
            <h3 className="text-xl font-semibold mb-2 text-center">{chartTitle}</h3>
            <div className="flex-grow">
              <Chart data={chartData} />
            </div>
          </div>
        ) : (
          <div className="text-gray-400 text-center">
            <p className="mb-2">No chart data available</p>
            <p className="text-sm">Run your code to generate a chart</p>
          </div>
        )}
      </div>
    </div>
  );
}
