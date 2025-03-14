import { useEffect } from "react";
import CodeMirror from '@uiw/react-codemirror';
import { python } from '@codemirror/lang-python';
import { vscodeDark } from '@uiw/codemirror-theme-vscode';

// Allowed imports and functions - used for validation
const ALLOWED_IMPORTS = ['pandas', 'numpy', 'pd', 'np'];
const ALLOWED_FUNCTIONS = ['system', 'quant_stats'];

export default function CodeEditor({
  pythonCode,
  setPythonCode,
  codeErrors,
  setCodeErrors,
  handleSubmit,
  isSubmitting,
  chartData,
  chartTitle,
  setChartTitle,
  description,
  setDescription,
  saveChart
}) {
  // Validate code for security issues
  useEffect(() => {
    validateCode(pythonCode);
  }, [pythonCode]);

  const validateCode = (code) => {
    const errors = [];
    
    // Check for unauthorized imports
    const importRegex = /^\s*import\s+([^\s]+)|^\s*from\s+([^\s]+)\s+import/gm;
    let match;
    while ((match = importRegex.exec(code)) !== null) {
      const importName = match[1] || match[2];
      if (!ALLOWED_IMPORTS.includes(importName)) {
        errors.push({
          line: code.substring(0, match.index).split('\n').length - 1,
          message: `Unauthorized import: ${importName}. Only pandas and numpy are allowed.`,
          severity: 'error'
        });
      }
    }
    
    // Check for potentially dangerous functions
    const dangerousFunctions = [
      'eval', 'exec', 'compile', 'open', 'file', '__import__', 
      'globals', 'locals', 'getattr', 'setattr', 'delattr', 
      'os', 'sys', 'subprocess', 'shutil'
    ];
    
    dangerousFunctions.forEach(func => {
      const funcRegex = new RegExp(`\\b${func}\\s*\\(`, 'g');
      let funcMatch;
      while ((funcMatch = funcRegex.exec(code)) !== null) {
        errors.push({
          line: code.substring(0, funcMatch.index).split('\n').length - 1,
          message: `Unauthorized function: ${func}() is not allowed for security reasons.`,
          severity: 'error'
        });
      }
    });
    
    setCodeErrors(errors);
  };

  return (
    <form onSubmit={handleSubmit} className="flex flex-col flex-grow">
      <div className="flex-grow relative">
        <CodeMirror
          value={pythonCode}
          height="100%"
          theme={vscodeDark}
          extensions={[python()]}
          onChange={(value) => setPythonCode(value)}
          className="border border-gray-300 rounded"
        />
        {codeErrors.length > 0 && (
          <div className="absolute top-2 right-2 bg-red-100 border border-red-300 text-red-700 px-2 py-1 rounded text-xs">
            {codeErrors.length} security {codeErrors.length === 1 ? 'error' : 'errors'}
          </div>
        )}
      </div>
      <div className="mt-4 flex space-x-4">
        <button
          type="submit"
          className={`px-4 py-2 text-white rounded ${codeErrors.length > 0 ? 'bg-red-600' : 'bg-blue-600'}`}
          disabled={isSubmitting || codeErrors.length > 0}
        >
          {isSubmitting ? "Running..." : codeErrors.length > 0 ? "Fix Errors to Run" : "Run Code"}
        </button>
        
        {chartData && (
          <div className="flex-1 flex space-x-2">
            <input
              type="text"
              placeholder="Chart title"
              className="flex-1 px-2 border border-gray-300 rounded"
              value={chartTitle}
              onChange={(e) => setChartTitle(e.target.value)}
            />
            <button
              type="button"
              onClick={saveChart}
              className="px-4 py-2 bg-green-600 text-white rounded"
            >
              Save Chart
            </button>
          </div>
        )}
      </div>
      
      {chartData && (
        <div className="mt-2">
          <textarea
            placeholder="Description (optional)"
            className="w-full px-2 py-1 border border-gray-300 rounded"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={2}
          />
        </div>
      )}
    </form>
  );
}
