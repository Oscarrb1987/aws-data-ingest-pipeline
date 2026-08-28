.DEFAULT_GOAL := help
SHELL := /bin/bash

help: ## Muestra esta ayuda
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

install: ## Instala dependencias de desarrollo
	python -m pip install --upgrade pip
	python -m pip install -e ".[dev]"

lint: ## Lint + formato
	ruff check src tests infra local
	ruff format --check src tests infra local

format: ## Aplica formato
	ruff format src tests infra local
	ruff check --fix src tests infra local

test: ## Ejecuta los tests unitarios
	pytest --cov=src --cov-report=term-missing -m "not integration"

test-all: ## Ejecuta todos los tests (requiere LocalStack)
	pytest --cov=src --cov-report=term-missing

up: ## Levanta LocalStack y crea los recursos de la demo
	docker compose -f local/docker-compose.yml up -d --wait
	python local/bootstrap.py

down: ## Para LocalStack y borra volumenes
	docker compose -f local/docker-compose.yml down -v

demo: ## Ejecuta el pipeline completo en local (caso correcto)
	python local/run_pipeline.py --dataset clientes --file sample_data/clientes_ok.csv

demo-ko: ## Ejecuta el pipeline con un fichero defectuoso (acaba en cuarentena)
	python local/run_pipeline.py --dataset clientes --file sample_data/clientes_ko.csv

demo-drift: ## Simula datos pisados entre la verificacion A y la B
	python local/run_pipeline.py --dataset clientes --file sample_data/clientes_ok.csv --simulate-drift

package: ## Empaqueta el codigo de las Lambdas en build/lambda
	bash scripts/package_lambda.sh

synth: package ## Sintetiza las plantillas CloudFormation
	cd infra && cdk synth

deploy: package ## Despliega en AWS (requiere credenciales)
	cd infra && cdk deploy --all --require-approval never

destroy: ## Elimina el stack de AWS
	cd infra && cdk destroy --all --force

.PHONY: help install lint format test test-all up down demo demo-ko demo-drift package synth deploy destroy
