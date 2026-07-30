FROM ghcr.io/prefix-dev/pixi:0.69.0

WORKDIR /opt/ubio-autobox
COPY pyproject.toml pixi.toml pixi.lock README.md LICENSE ./
COPY src ./src
RUN pixi install --locked

ENV DAGSTER_HOME=/opt/dagster/dagster_home
ENTRYPOINT ["pixi", "run"]
