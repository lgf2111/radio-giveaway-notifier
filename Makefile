.PHONY: install install-audio test lint fmt run lock clean mac-install mac-uninstall

# Create the venv and install core + dev dependencies (no audio/torch).
install:
	uv venv
	uv sync --extra dev

# Opt-in: also install the optional audio extra (pulls faster-whisper + torch).
install-audio:
	uv venv
	uv sync --extra dev --extra audio

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

# Install the macOS launchd LaunchAgent (idempotent; see deploy/macos/).
mac-install:
	bash deploy/macos/install.sh

# Stop and remove the macOS LaunchAgent (keeps config/logs).
mac-uninstall:
	bash deploy/macos/uninstall.sh

# Regenerate the lockfile after changing dependencies.
lock:
	uv lock

# Remove the venv, caches, and local dedupe databases.
clean:
	rm -rf .venv __pycache__ .pytest_cache .ruff_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -f *.db
