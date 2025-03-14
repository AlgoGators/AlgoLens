export default function DebugPanel({ response, debugOutput }) {
    return (
      <div className="mt-4 flex-grow">
        <h2 className="text-xl font-bold mb-2">Debug Output</h2>
        <div className="border border-gray-300 rounded p-2 h-full flex flex-col">
          {/* Output from Python execution */}
          {response && (
            <div className="mb-4">
              <h3 className="font-bold text-sm mb-1">Execution Output:</h3>
              <pre className="bg-gray-100 p-2 rounded text-sm overflow-auto max-h-32">
                {response}
              </pre>
            </div>
          )}
          
          {/* Debug messages */}
          <div className="flex-grow overflow-auto">
            <h3 className="font-bold text-sm mb-1">Debug Messages:</h3>
            <div className="text-sm">
              {debugOutput.map((msg, index) => (
                <div 
                  key={index} 
                  className={`mb-1 p-1 rounded ${
                    msg.type === 'Error' ? 'bg-red-100 text-red-800' : 
                    msg.type === 'Warning' ? 'bg-yellow-100 text-yellow-800' : 
                    msg.type === 'Success' ? 'bg-green-100 text-green-800' : 
                    'bg-blue-100 text-blue-800'
                  }`}
                >
                  <span className="text-xs text-gray-500">[{msg.timestamp}]</span>{' '}
                  <span className="font-bold">{msg.type}:</span> {msg.message}
                </div>
              ))}
              {debugOutput.length === 0 && (
                <div className="text-gray-500 italic">No messages yet. Run your code to see output.</div>
              )}
            </div>
          </div>
        </div>
      </div>
    );
  }
  