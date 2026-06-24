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
	parse-example parse-lenna parse-lenna-online parse-google parse-localhost \
	run run-example run-lenna run-google run-lenna-tui run-example-tui run-localhost serve clean

LOCALHOST_PORT ?= 8765
LOCALHOST_URL := http://127.0.0.1:$(LOCALHOST_PORT)/pages/basic.html

help:
	@echo "Offline browser — common targets"
	@echo ""
	@echo "  Generated files live under $(TMP_ROOT)/"
	@echo ""
	@echo "  make setup              Create venv and install dependencies"
	@echo "  make test               Run offline smoke tests (example + local Lenna)"
	@echo "  make test-all           Run all tests, including live Wikipedia fetch"
	@echo "  make parse-example      Build $(DOM_JSON) from example.html"
	@echo "  make parse-lenna        Build $(LENNA_JSON) from local lenna.html"
	@echo "  make parse-lenna-online Fetch and build Lenna.json from Wikipedia"
	@echo "  make run-example        Open the example page in the Qt viewer"
	@echo "  make parse-google        Build Google.json from google.com"
	@echo "  make run-google          Open Google in the Qt viewer (with search bar)"
	@echo "  make test-localhost     Fetch test pages from local webserver and verify JS translation"
	@echo "  make serve              Run localhost test webserver (pages under testserver/pages/)"
	@echo "  make parse-localhost    Build Localhost.json from the running test server"
	@echo "  make run-localhost      Open basic localhost test page in the Qt viewer"
	@echo "  make run-localhost-images Start server and open upload/download test pages"
	@echo "  make run-example-tui     View example page in the terminal"
	@echo "  make clean              Remove generated files from $(TMP_ROOT)"

setup: $(VENV)/bin/python
	$(PIP) install -r requirements.txt

install: setup

$(VENV)/bin/python:
	$(PYTHON) -m venv $(VENV)

test: setup test-js2qt parse-example parse-lenna
	@QT_QPA_PLATFORM=offscreen $(PY) smoke_test.py example lenna
	@QT_QPA_PLATFORM=offscreen $(PY) smoke_test.py google google-search
	@QT_QPA_PLATFORM=offscreen $(PY) smoke_test.py render
	@$(PY) smoke_test.py tui sixel sixel-cache tui-store
	@$(PY) testserver/test_js_pipeline.py
	@echo "All smoke tests passed."

test-all: setup test parse-lenna-online

test-js2qt:
	@echo "==> js2qt: alert translation"
	@echo "function demo(){alert('ok');}" | $(PY) js2qt.py | grep -q "QMessageBox.information"
	@echo "    ok"

test-example:
	@QT_QPA_PLATFORM=offscreen $(PY) smoke_test.py example

test-lenna:
	@QT_QPA_PLATFORM=offscreen $(PY) smoke_test.py lenna

test-render:
	@QT_QPA_PLATFORM=offscreen $(PY) smoke_test.py render

parse-example: setup
	$(PY) www2json.py $(EXAMPLE_HTML) $(DOM_JSON)

parse-lenna: setup
	@test -f $(LENNA_HTML) || { \
		echo "Missing $(LENNA_HTML). Run:"; \
		echo "  curl -fsSL '$(LENNA_URL)' -o $(LENNA_HTML)"; \
		exit 1; \
	}
	$(PY) www2json.py $(LENNA_HTML) $(LENNA_JSON)

parse-lenna-online: setup
	$(PY) www2json.py "$(LENNA_URL)" $(LENNA_JSON)
	@$(MAKE) test-lenna

run-example: parse-example
	$(PY) json2qt.py $(DOM_JSON)

parse-google: setup
	$(PY) www2json.py "https://www.google.com/?gbv=1" $(GOOGLE_JSON)

run-google: setup
	$(PY) json2qt.py --online

run-lenna: parse-lenna
	$(PY) json2qt.py $(LENNA_JSON)

test-localhost: setup
	$(PY) testserver/test_js_pipeline.py

serve: setup
	$(PY) testserver/server.py --port $(LOCALHOST_PORT)

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
