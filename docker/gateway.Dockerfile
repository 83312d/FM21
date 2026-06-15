# Pinned tag; CI/dev may override via build-arg when Docker Hub TLS is unavailable.
# U33: nginx-gateway.conf defines limit_req zones (geo + webhook) and static cache headers.
ARG NGINX_IMAGE=nginx:1.27-alpine
FROM ${NGINX_IMAGE}

COPY docker/nginx-gateway.conf /etc/nginx/conf.d/default.conf
COPY web/ /usr/share/nginx/html/

EXPOSE 80
