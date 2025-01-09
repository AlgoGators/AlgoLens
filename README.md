# Algo Trading Dashboard

A web application for displaying algorithmic trading portfolio information and metrics.

## Prerequisites

- Node.js (LTS version recommended, v20.10.0)
- npm (comes with Node.js)

## Getting Started

1. Clone the repository:

```bash
git clone https://github.com/AlgoGators/AlgoLens.git algo-lens
cd algo-lens
```

2. Install dependencies:

```bash
npm install
```

3. Start the development server:

```bash
npm run dev
python app.py
```

The application will be available at `http://localhost:3000` and Flask will run on `http://localhost:5000`

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

1. Create a feature branch
2. Make your changes
3. Submit a pull request

## License

[Apache 2.0]("./LICENSE") Algo-Lens
