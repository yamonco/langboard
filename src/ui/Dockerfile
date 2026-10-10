FROM node:22
WORKDIR /app

RUN apt-get update && apt-get install -y

COPY ./ui /app
COPY ./shared/ts /shared/ts
COPY ./sdk/vendor /sdk/vendor

RUN cd /shared/ts && yarn install && yarn run build && yarn link

RUN yarn config set registry "http://registry.npmjs.org"

RUN cd /app && yarn install --network-timeout 100000
