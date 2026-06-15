# FM21 production gateway (U30) — HTTP listener, prod nginx routes.
ARG NGINX_IMAGE=nginx:1.27-alpine
FROM ${NGINX_IMAGE}

COPY deploy/production/gateway/nginx.conf /etc/nginx/conf.d/default.conf
COPY web/ /usr/share/nginx/html/

EXPOSE 80
