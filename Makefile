.DEFAULT_GOAL := help

COMPOSE := docker compose

.PHONY: help setup config build up down logs ps health migrate test e2e clean

help: ## Lista os comandos
	@awk 'BEGIN {FS = ":.*## "}; /^[a-zA-Z_-]+:.*## / {printf "%-12s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

setup: ## Cria .env local sem sobrescrever
	@test -f .env || cp .env.example .env
	@echo "Revise os segredos em .env antes de subir os serviços."

config: ## Valida e renderiza o Compose
	$(COMPOSE) --env-file .env config --quiet

build: ## Constrói API, worker e web
	$(COMPOSE) build

up: ## Inicia a pilha local
	$(COMPOSE) up -d --build

down: ## Para a pilha preservando dados
	$(COMPOSE) down

logs: ## Acompanha logs dos serviços
	$(COMPOSE) logs -f --tail=200

ps: ## Mostra estado e healthchecks
	$(COMPOSE) ps

health: ## Verifica endpoints locais
	curl --fail http://localhost:$${API_PORT:-8080}/api/v1/health
	curl --fail http://localhost:$${WEB_PORT:-3000}/login

migrate: ## Aplica migrações Alembic no container da API
	$(COMPOSE) exec api alembic upgrade head

test: ## Testes da API e worker, lint e typecheck da web
	cd apps/api && python -m pytest -q
	cd apps/web && npm run lint && npx tsc --noEmit

e2e: ## Smoke Playwright contra a pilha em execução
	cd apps/web && npx playwright test

clean: ## Remove contêineres e volumes locais (destrutivo)
	@echo "Use 'docker compose down --volumes' conscientemente; este alvo não apaga dados."
