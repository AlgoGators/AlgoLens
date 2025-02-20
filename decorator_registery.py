import os
import importlib
import inspect
from functools import wraps

def discover_decorated_functions(base_dir):
    """
    Discover and import all Python files from a directory recursively.
    Populate the `decorated_functions` registry.

    Parameters:
    - base_dir (str): Path to the base directory for discovery.
    """
    excluded_dirs = {'venv', 'node_modules', '__pycache__', 'AlgoLens', '.git', 'optimizers'}  # Directories to skip
    for root, dirs, files in os.walk(base_dir):
        # Modify dirs in-place to skip excluded directories
        dirs[:] = [d for d in dirs if d not in excluded_dirs]

        for file in files:
            if file.endswith(".py") and not file.startswith("__"):
                #print(f"Processing file: {file}")
                # Build module path relative to base_dir and convert to module notation
                module_path = os.path.relpath(os.path.join(root, file), start=base_dir)
                module_name, _ = os.path.splitext(module_path.replace(os.sep, "."))
                #print(f"Attempting to import module: {module_name}")

                try:
                    module = importlib.import_module(module_name)
                    #print(f"Module '{module_name}' imported successfully.")
                    
                    # Trigger decorators by accessing module content and list all functions
                    #for name, obj in inspect.getmembers(module, inspect.isfunction):
                    #    print(f"Found function: {name}")
                    #    if name in decorated_functions:
                    #        print(f"Discovered decorated function: {name}")
                except Exception as e:
                    print(f"Error importing {module_name}: {e}")

decorated_functions = {}

def AlgoLens(func):
    """Decorator to register decorated functions."""
    decorated_functions[func.__name__] = func
    @wraps(func)
    def wrapper(*args, **kwargs):
        print(f"Executing {func.__name__}...")
        return func(*args, **kwargs)
    return wrapper