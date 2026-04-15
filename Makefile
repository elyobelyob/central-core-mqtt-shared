.PHONY: venv install test cov clean

VENV := .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

venv:
	python3 -m venv $(VENV)

install: venv
	$(PIP) install -U pip
	$(PIP) install -e '.[dev]'

test:
	$(VENV)/bin/pytest

cov:
	$(VENV)/bin/pytest --cov-report=html

clean:
	rm -rf .pytest_cache .coverage coverage.xml htmlcov build dist *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} +
