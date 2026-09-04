.PHONY: install demo eval test audit-verify lint api web seed serve compose ci e2e

PY ?= $(shell [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)
export PYTHONPATH := apps/api:$(PYTHONPATH)

install:
	$(PY) -m pip install -e ".[dev]"
	cd apps/web && ( [ -f package-lock.json ] && npm ci || npm install )

seed:
	$(PY) -m rekha.cli seed

eval:
	$(PY) -m rekha.cli eval

demo: seed eval
	@echo "Eval report: artifacts/eval/report.md"
	@echo "Start API with: make api"
	@echo "Start web with: make web"

api:
	$(PY) -m uvicorn rekha.api:app --reload --host 0.0.0.0 --port 8080

web:
	cd apps/web && npm run dev -- --port 3000 --hostname 0.0.0.0

serve:
	bash scripts/dev.sh

compose:
	docker compose -f infra/docker-compose.yml up --build

compose-full:
	docker compose -f infra/docker-compose.yml -f infra/docker-compose.full.yml --profile full up --build

audit-verify:
	$(PY) -m rekha.cli audit-verify

test:
	$(PY) -m pytest -q --cov=rekha --cov-fail-under=85

lint:
	$(PY) -m ruff check apps/api tests packages

ci:
	$(PY) -m ruff check apps/api tests packages
	$(PY) -m pytest -q --cov=rekha --cov-fail-under=85
	$(PY) -m rekha eval
	cd apps/web && npm run lint && npm test && npx tsc --noEmit && npm run build

e2e:
	cd apps/web && npx playwright test
