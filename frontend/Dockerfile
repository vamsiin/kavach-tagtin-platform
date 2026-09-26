# ---- build the React app ----------------------------------------------------
FROM node:20-alpine AS build
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# The browser calls the API on the same host under /api (nginx proxies it to the
# backend container), so no CORS and no port 8000 exposed to users.
ENV VITE_API_URL=/api
RUN npm run build

# ---- serve it with nginx ------------------------------------------------------
FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /src/dist /usr/share/nginx/html
EXPOSE 80
