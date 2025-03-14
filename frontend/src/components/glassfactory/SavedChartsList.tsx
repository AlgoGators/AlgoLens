export default function SavedChartsList({ savedCharts, loadChart, deleteChart }) {
    if (savedCharts.length === 0) {
      return null;
    }
    
    return (
      <div>
        <h2 className="text-xl font-bold mb-2">Local Charts</h2>
        <div className="border border-gray-300 rounded p-2 max-h-60 overflow-y-auto">
          {savedCharts.map((chart, index) => (
            <div 
              key={index} 
              className="p-2 hover:bg-gray-100 cursor-pointer flex justify-between items-center border-b last:border-b-0"
            >
              <span 
                className="flex-1"
                onClick={() => loadChart(chart)}
              >
                {chart.title}
                {chart.filepath && (
                  <span className="ml-2 text-xs text-green-600">
                    (saved on server)
                  </span>
                )}
              </span>
              <div className="flex space-x-2">
                <span className="text-xs text-gray-500">
                  {new Date(chart.createdAt).toLocaleDateString()}
                </span>
                <button 
                  onClick={(e) => deleteChart(index, e)}
                  className="text-red-500 text-xs"
                >
                  Delete
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  }
  