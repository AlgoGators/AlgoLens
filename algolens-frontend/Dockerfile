# Build stage
FROM node:26-alpine@sha256:0b36e8c136b94cd4fcf02188228e76c31ad5872eef3fec8cbd2eee500cfd9e80 AS build

WORKDIR /app

# Copy package files
COPY package*.json ./

# Install dependencies
RUN npm ci

# Copy source code
COPY . .

# Build argument for API URL
ARG VITE_API_URL
ENV VITE_API_URL=$VITE_API_URL
ARG APP_RELEASE_SHA=development
ENV APP_RELEASE_SHA=$APP_RELEASE_SHA

# Build the application
RUN npm run build
RUN node -e "const fs=require('fs');const sha=process.env.APP_RELEASE_SHA;if(sha!=='development'&&!/^[0-9a-f]{40}$/.test(sha||''))throw Error('Invalid release SHA');fs.writeFileSync('build/release.json',JSON.stringify({release:sha==='development'?null:sha}));"

# Production stage
FROM nginx:alpine@sha256:df221db836e1754089190208cee7eeda94f233197056426eda74a43ab1abeac2
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy built assets from build stage
COPY --from=build /app/build /usr/share/nginx/html

# Expose port 80
EXPOSE 80

# Start nginx
CMD ["nginx", "-g", "daemon off;"]
