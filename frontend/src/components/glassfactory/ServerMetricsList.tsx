export default function ServerMetricsList({ serverMetrics, isLoading, loadServerMetric }) {
    if (serverMetrics.length === 0 && !isLoading) {
      return null;
    }
    
    return (
      <div>
        <h2 className="text-xl font-bold mb-2">Server Metrics</h2>
        <div className="border border-gray-300 rounded p-2 max-h-60 overflow-y-auto">
          {isLoading ? (
            <div className="text-center py-4 text-gray-500">
              Loading metrics from server...
            </div>
          ) : serverMetrics.length === 0 ? (
            <div className="text-center py-4 text-gray-500">
              No metrics found on server
            </div>
          ) : (
            serverMetrics.map((metric, index) => (
              <div 
                key={index}
                className="p-2 hover:bg-gray-100 cursor-pointer border-b last:border-b-0"
                onClick={() => loadServerMetric(metric.filename)}
              >
                <div className="font-medium">{metric.name}</div>
                {metric.description && (
                  <div className="text-xs text-gray-600">{metric.description}</div>
                )}
                <div className="text-xs text-gray-500 mt-1">
                  Created: {new Date(metric.created_at).toLocaleString()}
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    );
  }
  