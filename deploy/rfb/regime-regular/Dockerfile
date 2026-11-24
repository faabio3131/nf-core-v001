# RTC-RFB-06: official Receita Federal Regime Regular (regime geral) RTC
# calculator, internal only. Built from the exact pinned commit (kept equal to
# REGIME_REGULAR_CALCULATOR_PIN by tests). MIT licensed. Port 8080, /api.
FROM maven:3.9-eclipse-temurin-25 AS build
ARG RFB_REPO=https://github.com/ReceitaFederal/calculadora-rtc-regime-regular.git
ARG RFB_COMMIT=f1eebd7ce3157423b1a6aaca7dc1d6c3395452c4
WORKDIR /src
RUN git init -q . \
 && git remote add origin "$RFB_REPO" \
 && git fetch -q --depth 1 origin "$RFB_COMMIT" \
 && git checkout -q FETCH_HEAD \
 && test "$(git rev-parse HEAD)" = "$RFB_COMMIT" \
 && mvn -q -B -DskipTests package \
 && cp target/api-regime-geral.jar /app.jar \
 && cp LICENSE /LICENSE.rfb

FROM eclipse-temurin:25-jre
RUN useradd --system --uid 10062 --home /app rtc && mkdir -p /app/calculadora/db \
 && chown -R rtc /app
COPY --from=build /app.jar /app/app.jar
COPY --from=build /LICENSE.rfb /app/LICENSE.rfb
WORKDIR /app
USER rtc
# Database from deploy/rfb/database, mounted read-only at /app/calculadora/db.
# The version comparator never calls the public pilot.
ENV VERSAO_OFFLINE_URL=http://127.0.0.1:9/disabled \
    APP_CORS_ALLOWED_ORIGINS=http://127.0.0.1 \
    JAVA_TOOL_OPTIONS="-XX:MaxRAMPercentage=70 -XX:+UnlockDiagnosticVMOptions -XX:-UseBASE64Intrinsics"
EXPOSE 8080
ENTRYPOINT ["java", "-Dspring.profiles.active=offline", "-jar", "/app/app.jar"]
