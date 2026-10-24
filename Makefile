BACKEND_HOST ?= 127.0.0.1
BACKEND_PORT ?= 18109
FRONTEND_HOST ?= 127.0.0.1
FRONTEND_PORT ?= 18185

.PHONY: setup setup-backend setup-frontend start models models-all models-tts models-voxcpm models-soulx-singer models-sfx dev dev-backend dev-frontend check check-release check-backend check-frontend build-frontend storybook build-storybook check-scripts install

setup: setup-backend setup-frontend

setup-backend:
	cd backend && uv sync --locked --inexact
	cd backend && if [ ! -f .env ]; then cp .env.example .env; fi

setup-frontend:
	cd frontend && pnpm install --frozen-lockfile
	cd frontend && if [ ! -f .env ]; then cp .env.example .env; fi

start:
	./start.sh

models: models-tts

models-all:
	./download-models.sh --all

models-tts:
	./download-models.sh --tts

models-voxcpm:
	./download-models.sh --voxcpm

models-soulx-singer:
	./download-models.sh --soulx-singer

models-sfx:
	./download-models.sh --sfx

dev:
	$(MAKE) -j2 dev-backend dev-frontend

dev-backend:
	cd backend && uv run uvicorn main:app --host $(BACKEND_HOST) --port $(BACKEND_PORT) --reload

dev-frontend:
	cd frontend && pnpm run dev --host $(FRONTEND_HOST) --port $(FRONTEND_PORT)

# Verification uses the existing env-directory override and never needs developer API keys.
check: export CLONE_VOICE_ENV_DIR := $(if $(CLONE_VOICE_ENV_DIR),$(CLONE_VOICE_ENV_DIR),$(CURDIR)/frontend/node_modules/.cache/verification-env)
check: check-release check-scripts check-backend check-frontend build-frontend

check-scripts:
	bash -n install.sh download-models.sh start.sh

check-release:
	python3 scripts/check_release.py

check-backend:
	cd backend && uv run --extra dev pytest tests

check-frontend:
	cd frontend && pnpm run test:unit
	cd frontend && pnpm run check

build-frontend:
	cd frontend && pnpm run build

storybook:
	cd frontend && pnpm run storybook

build-storybook:
	cd frontend && pnpm run build-storybook

install:
	./install.sh
