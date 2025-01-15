import os
import importlib
import inspect

def discover_decorated_functions(base_dir):
    """
    Discover and import all Python files from a directory recursively.
    Populate the `decorated_functions` registry.

    Parameters:
    - base_dir (str): Path to the base directory for discovery.
    """
    excluded_dirs = {'venv', 'node_modules', '__pycache__'}  # Directories to skip
    for root, dirs, files in os.walk(base_dir):
        # Modify dirs in-place to skip excluded directories
        dirs[:] = [d for d in dirs if d not in excluded_dirs]

        for file in files:
            if file.endswith(".py") and not file.startswith("__"):
                module_path = os.path.relpath(os.path.join(root, file), start=base_dir)
                module_name = module_path.replace(os.sep, ".").rstrip(".py")

                try:
                    module = importlib.import_module(module_name)
                    # Trigger decorators by accessing module content
                    for name, obj in inspect.getmembers(module, inspect.isfunction):
                        if name in decorated_functions:  # Check if function is in the registry
                            print(f"Discovered decorated function: {name}")
                except Exception as e:
                    pass

# decorator_registry.py (or within the same file as algo_scope)
decorated_functions = {}

def AlgoLens(func):
    """Decorator to register decorated functions."""
    decorated_functions[func.__name__] = func
    def wrapper(*args, **kwargs):
        print(f"Executing {func.__name__}...")
        return func(*args, **kwargs)
    return wrapper

