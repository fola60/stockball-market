FROM node:22-alpine

WORKDIR /app
COPY services/admin-ui/package.json services/admin-ui/package-lock.json ./
RUN npm ci
COPY services/admin-ui ./

EXPOSE 3001
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "3001"]
