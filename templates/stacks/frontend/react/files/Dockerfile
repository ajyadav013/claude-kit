FROM node:22-alpine

WORKDIR /app

# Install dependencies first for better layer caching (no lockfile yet -> npm install).
COPY package.json ./
RUN npm install

COPY . .

EXPOSE 5173

# Dev server, bound to all interfaces so it is reachable from the host via the mapped port.
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
