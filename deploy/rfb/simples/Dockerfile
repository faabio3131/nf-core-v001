# RTC-RFB-02: official Receita Federal Simples Nacional RTC calculator, internal only.
# Built from the exact pinned commit (kept equal to SIMPLES_CALCULATOR_PIN in
# src/kordena_fiscal/tax/rfb_simples_calculator.py by tests). MIT licensed.
FROM maven:3.9-eclipse-temurin-25 AS build
ARG RFB_REPO=https://github.com/ReceitaFederal/calculadora-rtc-simples-nacional.git
ARG RFB_COMMIT=a926d5a76095ac0295a6612a9a54db7ffead2396
WORKDIR /src
RUN git init -q . \
 && git remote add origin "$RFB_REPO" \
 && git fetch -q --depth 1 origin "$RFB_COMMIT" \
 && git checkout -q FETCH_HEAD \
 && test "$(git rev-parse HEAD)" = "$RFB_COMMIT" \
 && mvn -q -B -DskipTests package \
 && cp target/api-simples-nacional.jar /app.jar \
 && cp LICENSE /LICENSE.rfb

FROM eclipse-temurin:25-jre
RUN useradd --system --uid 10061 --home /app rtc && mkdir -p /app/calculadora/db \
 && chown -R rtc /app
COPY --from=build /app.jar /app/app.jar
COPY --from=build /LICENSE.rfb /app/LICENSE.rfb
WORKDIR /app
USER rtc
# Database from deploy/rfb/database (shared with the regime-regular calculator),
# mounted read-only at /app/calculadora/db/calculadora-pro.db.
# VERSAO_URL points nowhere so the offline comparator never calls the public pilot.
ENV VERSAO_URL=http://127.0.0.1:9/disabled \
    VERSAO_AMBIENTE=nfcore-offline \
    APP_CORS_ALLOWED_ORIGINS=http://127.0.0.1 \
    JAVA_TOOL_OPTIONS="-XX:MaxRAMPercentage=70 -XX:+UnlockDiagnosticVMOptions -XX:-UseBASE64Intrinsics"
EXPOSE 8082
ENTRYPOINT ["java", "-Dspring.profiles.active=offline", "-jar", "/app/app.jar"]
