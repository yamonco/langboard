FROM node:22@sha256:0e5f906573693feaa1e21057ebdcfdb5bd5021f050b2dc7c9deceb629c7da2a8 AS build
WORKDIR /work

COPY src/shared/ts/package.json src/shared/ts/yarn.lock ./src/shared/ts/
RUN --mount=type=cache,target=/usr/local/share/.cache/yarn cd src/shared/ts && yarn install --frozen-lockfile --network-concurrency 4 --network-timeout 120000
COPY src/shared/ts ./src/shared/ts
RUN cd src/shared/ts && yarn build

COPY src/sdk/vendor ./src/sdk/vendor
COPY src/ui/package.json src/ui/yarn.lock ./src/ui/
RUN --mount=type=cache,target=/usr/local/share/.cache/yarn cd src/ui && yarn install --frozen-lockfile --network-concurrency 4 --network-timeout 120000
COPY src/ui ./src/ui
COPY scripts/run-profile-validation.sh ./scripts/run-profile-validation.sh
WORKDIR /work/src/ui
ARG PROJECT_NAME=Langboard
ARG PROJECT_SHORT_NAME=LB
ARG API_URL
ARG PUBLIC_UI_URL
ARG SOCKET_URL
ARG PUBLIC_SENTRY_DSN=""
ARG PUBLIC_SENTRY_ENVIRONMENT=""
ARG PUBLIC_SENTRY_RELEASE=""
ARG IS_OLLAMA_RUNNING=false
ARG MAX_FILE_SIZE_MB=50
ARG NODE_BUILD_HEAP_MB=3072
RUN NODE_OPTIONS="--max-old-space-size=${NODE_BUILD_HEAP_MB}" yarn build

FROM build AS validation-ui-source
RUN mkdir -p /result /work/src/ui/test-results && chown node:node /result /work/src/ui/test-results
USER node

FROM validation-ui-source AS validation-ui
ENV PROFILE=ui
RUN bash /work/scripts/run-profile-validation.sh

FROM scratch AS validation-ui-results
COPY --from=validation-ui /result/ /result/

FROM nginxinc/nginx-unprivileged:stable-alpine@sha256:15c994d10d6d78658721c3bcafff14cb281fba2a4bdf9d5ba92c416a472516e3 AS runtime
USER root
RUN apk add --no-cache 'tiff>=4.7.2-r0'
COPY docker/ui-nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /work/src/ui/dist /usr/share/nginx/html
USER 101:101
EXPOSE 8080
