# ── Build stage ──
FROM node:22-slim AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install
COPY . .
RUN npm run build

# ── Production stage ──
FROM nginx:alpine
RUN apk add --no-cache apache2-utils
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 3000
CMD ["/docker-entrypoint.sh"]
