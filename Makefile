BACKEND_HOST ?= 127.0.0.1
BACKEND_PORT ?= 8000
FRONTEND_HOST ?= 127.0.0.1
FRONTEND_PORT ?= 5174

.PHONY: setup setup-backend setup-frontend models models-all models-tts models-omnivoice models-voxcpm models-cosyvoice models-seed-vc dev dev-backend dev-frontend check check-backend check-frontend build-frontend

setup: setup-backend setup-frontend

setup-backend:
	cd backend && uv sync
	cd backend && cp -n .env.example .env

setup-frontend:
	cd frontend && pnpm install
	cd frontend && cp -n .env.example .env

models: models-all

models-all:
	./download-models.sh --all

models-tts:
	./download-models.sh --tts

models-cosyvoice:
	./download-models.sh --cosyvoice

models-omnivoice:
	./download-models.sh --omnivoice

models-voxcpm:
	./download-models.sh --voxcpm

models-seed-vc:
	./download-models.sh --seed-vc

dev:
	$(MAKE) -j2 dev-backend dev-frontend

dev-backend:
	cd backend && uv run uvicorn main:app --host $(BACKEND_HOST) --port $(BACKEND_PORT) --reload

dev-frontend:
	cd frontend && pnpm run dev --host $(FRONTEND_HOST) --port $(FRONTEND_PORT)

check: check-backend check-frontend build-frontend

check-backend:
	cd backend && uv run pytest tests

check-frontend:
	cd frontend && pnpm run check

build-frontend:
	cd frontend && pnpm run build
