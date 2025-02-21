# Algo Trading Dashboard

A web application for displaying algorithmic trading portfolio information and metrics.

## Prerequisites

- Node.js (LTS version recommended, v20.10.0)
- npm (comes with Node.js)

## Note

- AlgoLens expects you to decorate a function with @AlgoLens in the same directory as the AlgoLens module.

E.g

```
Your_Project/
├── AlgoLens/
│   ├── backend/
│   ├── frontend/
│   ├── ... 
│   └── app.py
└── Your_system.py  # Contains the function decorated with @AlgoLens
```

## Getting Started

1. Clone the repository:

```bash
git clone https://github.com/AlgoGators/AlgoLens.git
```

2. Install python dependencies:

Create a virtual environment if one has not already been created  
Mac
```bash
python3 -m venv venv
source venv/bin/activate
```

Windows
```bash
python -m venv venv
venv\Scripts\activate
```

This installs the requirements.txt and makes "algolens start" and alias for "python ./AlgoLens/backend/app.py"
```bash
cd AlgoLens
pip install -e .
```

4. Start the flask server from inside the AlgoLens/ file:

```bash
algolens start
```

3. Install npm dependencies:

```bash
cd AlgoLens/frontend
npm install
```

5. Start the npm server from inside the AlgoLens/frontend/ file:

In another terminal:
```bash
npm run dev
```

The application will be available at `http://localhost:3000` and Flask will run on `http://localhost:5000`

## How to use
AlgoLens accesses the return value of a function and passes it to app.py for processing and then to DashboardContent.tsx for presentation.

In order to integrate AlgoLens to your backtesting module, clone this repository and import the AlgoLens decorator (e.g from AlgoLens.app import Algolens -- may change depending on your file structure). 

For example:
```python
from AlgoLens import AlgoLens

@AlgoLens
def backtest_function():
    '''
    This function must return a pd.Series with 1 column named 'Date' and
    another column named 'Value' with the PRICE values of the strategy.
    '''
    ...
    ...
    ...
```
Upon refreshing the application, AlgoLens will parse your files for functions decorated with @AlgoLens fetch the respective function.

Please contact the contributors of this repository for more assistance.

## Project Structure

```
src/
├── app/                    # Next.js app directory
│   ├── dashboard/         # Dashboard page
│   └── login/            # Login page
├── components/           # React components
│   ├── auth/            # Authentication components
│   └── ui/              # UI components (shadcn/ui)
└── lib/                 # Utility functions
```

## Available Scripts

- `npm run dev` - Start development server
- `npm run build` - Build for production
- `npm start` - Start production server
- `npm run lint` - Run ESLint

## Key Features

- User authentication
- Portfolio value display
- Performance metrics
- Position tracking

## Tech Stack

- Next.js
- TypeScript
- Tailwind CSS
- shadcn/ui components

## Development Notes

- Component library documentation can be found in the shadcn/ui docs
- Tailwind CSS is used for styling
- Components are built using TypeScript for type safety

## Contributing

1. Clone the Master branch
2. Make your changes
3. Submit a pull request

## License

[Apache 2.0]("./LICENSE") Algo-Lens
