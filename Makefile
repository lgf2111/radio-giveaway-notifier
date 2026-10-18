.PHONY: install test lint fmt run lock clean

# Create the venv and install core + dev + optional audio dependencies.
install:
	uv venv
	uv sync --extra audio

# Run the full test suite.
test:
	uv run pytest

# Lint the project.
lint:
	uv run ruff check .

# Auto-format the project.
fmt:
	uv run ruff format .

# Offline demo: print detections from the bundled fixtures.
run:
	uv run python -m hotline once --dry-run

# Regenerate the lockfile after changing dependencies.
lock:
	uv lock

# Remove the venv, caches, and local dedupe databases.
clean:
	rm -rf .venv __pycache__ .pytest_cache .ruff_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -f *.db
