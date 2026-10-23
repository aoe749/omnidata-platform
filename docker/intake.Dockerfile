FROM node:25-slim AS build
WORKDIR /app
COPY services/intake/package.json services/intake/package-lock.json ./
RUN npm ci
COPY services/intake/tsconfig.json services/intake/tsconfig.build.json ./
COPY services/intake/src ./src
RUN npm run build

FROM node:25-slim
ENV NODE_ENV=production
WORKDIR /app
COPY services/intake/package.json services/intake/package-lock.json ./
RUN npm ci --omit=dev && npm cache clean --force
COPY --from=build /app/dist ./dist

# Run as an unprivileged user (the node image ships one).
USER node
EXPOSE 3000
CMD ["node", "dist/src/server.js"]
