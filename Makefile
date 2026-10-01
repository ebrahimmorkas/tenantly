.PHONY: install run test lint format migrate seed worker beat up down billing

install:
	pip install -r requirements-dev.txt

run:
	python manage.py runserver

migrate:
	python manage.py migrate

seed:
	python manage.py seed_demo

test:
	pytest --cov --cov-report=term-missing:skip-covered

lint:
	ruff check .
	ruff format --check .

format:
	ruff check --fix .
	ruff format .

worker:
	celery -A config worker --loglevel=info

beat:
	celery -A config beat --loglevel=info

up:
	docker compose up --build

down:
	docker compose down

billing:
	python manage.py run_billing
