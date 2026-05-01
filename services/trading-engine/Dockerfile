FROM rust:1-slim AS builder

WORKDIR /app

COPY services/trading-engine/Cargo.toml services/trading-engine/Cargo.lock ./
COPY services/trading-engine/src ./src

RUN cargo build --release

FROM debian:bookworm-slim

WORKDIR /app

COPY --from=builder /app/target/release/stockball-trading-engine /usr/local/bin/stockball-trading-engine

EXPOSE 3000

CMD ["stockball-trading-engine"]
