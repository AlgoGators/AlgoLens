FROM node:20-alpine

WORKDIR /app

# Copy package files for better caching
COPY frontend/package*.json ./

# Install dependencies
RUN npm install
RUN npm audit fix

# Copy frontend files
COPY frontend/ ./

# Command to start development server
CMD ["npm", "run", "dev"]