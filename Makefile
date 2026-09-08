.PHONY: check test lint contracts

PYTHON ?= python3

check: lint test contracts

lint:
	cd services/api && $(PYTHON) -m ruff check app tests && $(PYTHON) -m pyright
	cd services/worker && $(PYTHON) -m ruff check app tests && $(PYTHON) -m pyright
	cd services/trading-engine && cargo fmt --all -- --check && cargo clippy --all-targets --all-features -- -D warnings
	cd services/admin-ui && npm run lint

test:
	cd services/api && $(PYTHON) -m pytest -q
	cd services/worker && $(PYTHON) -m pytest -q
	cd services/trading-engine && cargo test
	cd services/admin-ui && npm test

contracts:
	$(PYTHON) -m pytest -q packages/contracts/tests
