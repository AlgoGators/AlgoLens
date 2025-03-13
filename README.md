# Algo Trading Dashboard

A web application for displaying algorithmic trading portfolio information and metrics.

For backtesters:
    AlgoLens reads the most recent backtesting entries from the database. These backtesting results are pulled to provide metrics and charts as performance metrics. You may customize additional metrics and charts yourself if you wish and request for them to be manually added.

## Prerequisites

- Node.js (LTS version recommended, v20.10.0)
- npm (comes with Node.js)

## To-Do

Portfolio:
- Portfolio-level charts/metrics
- Asset-level charts/metrics
- Customizable charts/metrics  --> GlassFactory
- Time-machine (user can observe held positions at certain moments in time)

Backtesting:
- ✔️ Portfolio-level charts/metrics
- ✔️ Strategy-level charts/metrics
- Customizable charts/metrics  --> GlassFactory
- Time-machine (user can observe backtesting results at certain intervals of time)

GlassFactory:
- Customizable charts/metrics
    - ✔️ User can run code
        - ✔️ Set up IDE with error warnings
        - ✔️ Access to a basic terminal for outputs
    - ✔️ User can manipulate data
    - ✔️ User can make and see charts/metrics
    - User can save code
    - User can use saved code as an additional feature for portfolio/backtesting
    - User can request for their code to be implemented

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

```bash
cd AlgoLens
pip install -r requirements.txt
```

3. Start the flask server from inside the AlgoLens/backend/ file:
Mac
```bash
cd backend
python3 app.py
```

Mac
```bash
cd backend
python app.py
```

4. Install npm dependencies from inside AlgoLens/frontend/ file:

```bash
cd frontend
npm install
npm fund
```

5. Start the npm server from inside the AlgoLens/frontend/ file:

In another terminal:
```bash
npm run dev
```

## Project Structure

```
AlgoLens
├── backend/
│   ├── __init__.py
│   ├── app.py                # Flask app (backend connection to next.js)
│   ├── data_access.py        # Database API
|   └── ...                   # Function decorator  
├── frontend/
│   ├── public/
│   ├── src/
│   │   ├── app/
│   │   │   ├── dashboard/    # Dashboard page
│   │   │   └── login/        # Login page
│   │   ├── components/
│   │   │   ├── auth/         # Authentication components
│   │   │   └── ui/           # UI components (shadcn/ui)
│   │   └── lib/              # Utility functions
│   ├── package.json          # Typescript and json config files
│   └── ...
├── .gitignore
├── LICENSE
├── README.md
├── requirements.txt
└── ...

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

## License

[Apache 2.0]("./LICENSE") Algo-Lens
