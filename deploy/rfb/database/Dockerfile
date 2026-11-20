# RTC-RFB-05: official calculator database (SQLite) generated from the pinned
# Receita Federal regime-regular repository (Flyway scripts live there, ADR009).
# Both calculators (Simples Nacional and Regime Regular) read this same file.
# Build:  docker build --output type=local,dest=<host-db-dir> deploy/rfb/database
FROM maven:3.9-eclipse-temurin-25 AS build
ARG RFB_REPO=https://github.com/ReceitaFederal/calculadora-rtc-regime-regular.git
ARG RFB_COMMIT=f1eebd7ce3157423b1a6aaca7dc1d6c3395452c4
ARG RFB_DB_VERSION=V0073
WORKDIR /src
RUN git init -q . \
 && git remote add origin "$RFB_REPO" \
 && git fetch -q --depth 1 origin "$RFB_COMMIT" \
 && git checkout -q FETCH_HEAD \
 && test "$(git rev-parse HEAD)" = "$RFB_COMMIT" \
 && mkdir -p calculadora/db \
 && mvn -q -B flyway:migrate -Dflyway.configFiles=./flyway/flyway-pro.conf --errors \
 && apt-get update -qq && apt-get install -y -qq sqlite3 >/dev/null \
 && test "$(sqlite3 calculadora/db/calculadora-pro.db \
      "select count(*) from flyway_schema_history where success = 0")" = "0" \
 && test "$(sqlite3 calculadora/db/calculadora-pro.db \
      "select VRBD_VERSAO_BASE_DADO from VERSAO_BASE_DADO order by VRBD_ID desc limit 1")" \
      = "$RFB_DB_VERSION" \
 && cp calculadora/db/calculadora-pro.db /calculadora-pro.db \
 && sha256sum /calculadora-pro.db > /calculadora-pro.db.sha256

FROM scratch
COPY --from=build /calculadora-pro.db /calculadora-pro.db
COPY --from=build /calculadora-pro.db.sha256 /calculadora-pro.db.sha256
