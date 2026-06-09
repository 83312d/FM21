# Pinned tag; CI/dev may override via build-arg when Docker Hub TLS is unavailable.
ARG NGINX_IMAGE=nginx:1.27-alpine
FROM ${NGINX_IMAGE}

COPY docker/nginx-gateway.conf /etc/nginx/conf.d/default.conf
COPY web/ /usr/share/nginx/html/

EXPOSE 80
