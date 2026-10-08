FROM node:22@sha256:0e5f906573693feaa1e21057ebdcfdb5bd5021f050b2dc7c9deceb629c7da2a8 AS build
WORKDIR /app

COPY shared/ts /shared/ts
RUN --mount=type=cache,target=/usr/local/share/.cache/yarn cd /shared/ts && yarn install --frozen-lockfile --network-concurrency 4 --network-timeout 120000 && yarn build

COPY socket /app
RUN --mount=type=cache,target=/usr/local/share/.cache/yarn yarn install --frozen-lockfile --network-concurrency 4 --network-timeout 120000 && yarn build
RUN --mount=type=cache,target=/usr/local/share/.cache/yarn yarn install --frozen-lockfile --production --network-concurrency 4 --network-timeout 120000
RUN --mount=type=cache,target=/usr/local/share/.cache/yarn cd /shared/ts && yarn install --frozen-lockfile --production --network-concurrency 4 --network-timeout 120000

FROM node:22@sha256:0e5f906573693feaa1e21057ebdcfdb5bd5021f050b2dc7c9deceb629c7da2a8
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*
WORKDIR /app
RUN mkdir -p /local /app/local && chown -R node:node /local /app/local
COPY --from=build --chown=node:node /shared/ts /shared/ts
COPY --from=build --chown=node:node /app/node_modules ./node_modules
COPY --from=build --chown=node:node /app/dist ./dist
COPY --from=build --chown=node:node /app/package.json ./package.json
USER 1000:1000
EXPOSE 5690
CMD ["node", "dist/index.js"]
