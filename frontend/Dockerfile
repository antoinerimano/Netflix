FROM node:22-alpine AS build
WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .
RUN npm run build

# The site's domain (SITE_DOMAIN in /opt/taurus/.env, passed by docker-compose.yml): the absolute
# links in index.html (canonical, Open Graph, JSON-LD) and robots.txt (sitemap) say __SITE_URL__
# in the sources. A build without it fails here rather than ship links to nowhere.
ARG SITE_DOMAIN
RUN test -n "$SITE_DOMAIN" || { echo "SITE_DOMAIN build argument missing (docker-compose.yml, /opt/taurus/.env)"; exit 1; }
RUN sed -i "s#__SITE_URL__#https://${SITE_DOMAIN}#g" build/index.html build/robots.txt && ! grep -l "__SITE_URL__" build/index.html build/robots.txt

FROM nginx:alpine
COPY --from=build /app/build /usr/share/nginx/html
