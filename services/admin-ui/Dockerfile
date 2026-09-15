FROM node:22-slim

WORKDIR /app
COPY services/admin-ui/package.json services/admin-ui/package-lock.json ./
RUN npm ci
COPY services/admin-ui ./
RUN npm run build

EXPOSE 3001
CMD ["npm", "run", "start", "--", "--hostname", "0.0.0.0", "--port", "3001"]
