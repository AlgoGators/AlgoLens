import sys
import os

# Determine the current directory (repo root) and add its parent to sys.path.
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from AlgoLens.backend.app import app

def main():
    if len(sys.argv) > 1 and sys.argv[1] == "start":
        app.run(debug=True)
    else:
        print("Usage: algolens start")

if __name__ == '__main__':
    main()