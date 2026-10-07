FROM node:22@sha256:0e5f906573693feaa1e21057ebdcfdb5bd5021f050b2dc7c9deceb629c7da2a8 AS build
WORKDIR /work

COPY src/shared/ts/package.json src/shared/ts/yarn.lock ./src/shared/ts/
RUN --mount=type=cache,target=/usr/local/share/.cache/yarn cd src/shared/ts && yarn install --frozen-lockfile
COPY src/shared/ts ./src/shared/ts
RUN cd src/shared/ts && yarn build

COPY src/ui/package.json src/ui/yarn.lock ./src/ui/
RUN --mount=type=cache,target=/usr/local/share/.cache/yarn cd src/ui && yarn install --frozen-lockfile
COPY src/ui ./src/ui
WORKDIR /work/src/ui
ARG PROJECT_NAME=Langboard
ARG PROJECT_SHORT_NAME=LB
ARG API_URL
ARG PUBLIC_UI_URL
ARG SOCKET_URL
ARG IS_OLLAMA_RUNNING=false
ARG MAX_FILE_SIZE_MB=50
RUN yarn build

FROM nginxinc/nginx-unprivileged:stable-alpine@sha256:15c994d10d6d78658721c3bcafff14cb281fba2a4bdf9d5ba92c416a472516e3
COPY docker/ui-nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /work/src/ui/dist /usr/share/nginx/html
USER 101:101
EXPOSE 8080
