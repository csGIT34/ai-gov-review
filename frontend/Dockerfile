# Placeholder web container (M0). The real React/Vite SPA is built in M8;
# this stage just serves a status page and reverse-proxies /api to the API.
FROM nginx:alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY index.html /usr/share/nginx/html/index.html
EXPOSE 80
