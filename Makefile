PYTHON ?= python3
VENV ?= .venv
PIP := $(VENV)/bin/pip
PY := $(VENV)/bin/python

EXAMPLE_HTML := example.html
LENNA_HTML ?= lenna.html
LENNA_URL := https://en.wikipedia.org/wiki/Lenna

TMP_ROOT := /tmp/offline-browser
BUNDLE_DIR := $(TMP_ROOT)/bundles
DOM_JSON := $(BUNDLE_DIR)/DOM.json
LENNA_JSON := $(BUNDLE_DIR)/Lenna.json
GOOGLE_JSON := $(BUNDLE_DIR)/Google.json
LOCALHOST_JSON := $(BUNDLE_DIR)/Localhost.json

.PHONY: help setup install test test-all test-js2qt test-example test-lenna test-google test-render test-tui test-localhost \
	parse-example parse-lenna parse-lenna-online parse-google parse-localhost parse-mock-search \
	run run-example run-lenna run-google run-lenna-tui run-example-tui run-localhost run-mock-search run-mock-search-viewer serve clean

LOCALHOST_PORT ?= 8765
LOCALHOST_URL := http://127.0.0.1:$(LOCALHOST_PORT)/pages/basic.html

help:
	@echo "Offline browser — common targets"
	@echo ""
	@echo "  Generated files live under $(TMP_ROOT)/"
	@echo ""
	@echo "  make setup              Create venv and install dependencies"
	@echo "  make test               Run the full automatic test suite (one command)"
	@echo "  make test-all           Same as test (alias)"
	@echo "  make parse-example      Build $(DOM_JSON) from example.html"
	@echo "  make parse-lenna        Build $(LENNA_JSON) (auto-fetch if needed)"
	@echo "  make run-example        Open the example page in the Qt viewer"
	@echo "  make parse-google       Build Google.json from google.com"
	@echo "  make run-google         Open Google in the Qt viewer (with search bar)"
	@echo "  make serve              Run localhost test webserver (includes mock search)"
	@echo "  make run-mock-search-viewer  Open Qt viewer against localhost mock search"
	@echo "  make run-xhr-search         Open Qt viewer on XHR-driven search page"
	@echo "  make parse-mock-search  Ingest mock search results into a bundle"
	@echo "  make clean              Remove generated files from $(TMP_ROOT)"

setup: $(VENV)/bin/python
	$(PIP) install -r requirements.txt

install: setup

$(VENV)/bin/python:
	$(PYTHON) -m venv $(VENV)

test test-all: setup
	@QT_QPA_PLATFORM=offscreen $(PY) run_tests.py

test-js2qt test-example test-lenna test-render test-tui test-localhost:
	@$(MAKE) test

parse-example: setup
	$(PY) www2json.py $(EXAMPLE_HTML) $(DOM_JSON)

parse-lenna: setup
	@$(PY) -c "from run_tests import prepare_bundles; prepare_bundles()"

parse-lenna-online: setup
	$(PY) www2json.py "$(LENNA_URL)" $(LENNA_JSON)

run-example: parse-example
	$(PY) json2qt.py $(DOM_JSON)

parse-google: setup
	$(PY) www2json.py "https://www.google.com/?gbv=1" $(GOOGLE_JSON)

run-google: setup
	$(PY) json2qt.py --online

run-lenna: parse-lenna
	$(PY) json2qt.py $(LENNA_JSON)

MOCK_SEARCH_HOME := http://127.0.0.1:$(LOCALHOST_PORT)/
MOCK_SEARCH_JSON := $(BUNDLE_DIR)/MockSearch.json
XHR_SEARCH_JSON := $(BUNDLE_DIR)/XHRSearch.json
XHR_SEARCH_URL := http://127.0.0.1:$(LOCALHOST_PORT)/pages/xhr-search.html

serve: setup
	$(PY) testserver/server.py --port $(LOCALHOST_PORT)

run-mock-search-viewer: setup
	OFFLINE_BROWSER_MOCK_SEARCH=$(MOCK_SEARCH_HOME) $(PY) json2qt.py --mock-search

run-mock-search-tui: setup
	OFFLINE_BROWSER_MOCK_SEARCH=$(MOCK_SEARCH_HOME) $(PY) json2tui.py --mock-search --interactive

parse-mock-search: setup
	@$(PY) -c "import urllib.request; urllib.request.urlopen('$(MOCK_SEARCH_HOME)', timeout=2)"
	$(PY) www2json.py "$(MOCK_SEARCH_HOME)search?q=python" $(MOCK_SEARCH_JSON)

run-mock-search: parse-mock-search
	OFFLINE_BROWSER_MOCK_SEARCH=$(MOCK_SEARCH_HOME) $(PY) json2qt.py $(MOCK_SEARCH_JSON)

run-xhr-search: setup
	@$(PY) -c "import urllib.request; urllib.request.urlopen('$(XHR_SEARCH_URL)', timeout=2)"
	$(PY) www2json.py "$(XHR_SEARCH_URL)" $(XHR_SEARCH_JSON)
	OFFLINE_BROWSER_MOCK_SEARCH=$(MOCK_SEARCH_HOME) $(PY) json2qt.py $(XHR_SEARCH_JSON)

parse-localhost: setup
	@$(PY) -c "import urllib.request; urllib.request.urlopen('$(LOCALHOST_URL)', timeout=2)"
	$(PY) www2json.py "$(LOCALHOST_URL)" $(LOCALHOST_JSON)

run-localhost-images: setup
	@echo "Open http://127.0.0.1:$(LOCALHOST_PORT)/pages/download.html"
	@echo "Open http://127.0.0.1:$(LOCALHOST_PORT)/pages/upload.html"
	$(PY) testserver/server.py --port $(LOCALHOST_PORT)

run-localhost: parse-localhost
	$(PY) json2qt.py $(LOCALHOST_JSON)

run-lenna-tui: parse-lenna
	$(PY) json2tui.py --interactive $(LENNA_JSON)

run-example-tui: parse-example
	$(PY) json2tui.py --interactive $(DOM_JSON)

run-google-tui: setup
	$(PY) json2tui.py --online --interactive

clean:
	rm -rf __pycache__ .pytest_cache $(TMP_ROOT)
