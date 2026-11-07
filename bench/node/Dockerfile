FROM node:22-slim@sha256:5ec23b7c622b00547753bc6ffd78085dd868a68aeb41c8e0a1418f033e13d96d
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev
COPY server.js .
# Un proceso (un núcleo), sin registro por solicitud: igual que el prototipo de FastAPI.
CMD ["node", "server.js"]
