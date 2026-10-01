# tmux-bellhop
#   make test        every tests/test_*.py on throwaway tmux servers (tests/run.sh)
#   make lint        shellcheck, bash -n, lint-portability, python syntax
#   make try         the fictional demo server, attached (never your own server)
#   make try-clean   remove it
#   make demos       render docs/img from demo/tapes with vhs
#   make scrub       the privacy check (plus the private denylist when
#                    SCRUB_DENYLIST_FILE is set)
#   make docs-check  key tables and images in the docs
#
# Works with the GNU make 3.81 that macOS ships. BASH_N=/bin/bash checks the
# bash 3.2 floor on macOS.

BASH_N ?= bash
PYTHON ?= python3
RENDER_DIR := /tmp/tmux-bellhop

SCRIPTS := $(wildcard bellhop.tmux bin/* lib/bellhop/*.sh libexec/* contrib/focus/* \
	demo/*.sh demo/bin/* scripts/*.sh tests/run.sh)

.PHONY: test lint try try-clean demos scrub docs-check

test:
	tests/run.sh

lint:
	shellcheck -x --severity=warning $(SCRIPTS)
	@for f in $(SCRIPTS); do $(BASH_N) -n "$$f" || exit 1; done; echo "bash -n: ok ($(BASH_N))"
	scripts/lint-portability.sh
	@$(PYTHON) -c 'import ast, sys; [ast.parse(open(f).read(), f) for f in sys.argv[1:]]' tests/*.py && \
		echo "python syntax: ok"

# $(call need,SCRIPT,TARGET): a clear message when another part of the repo is missing.
need = @test -f $(1) || { echo "make $(2): $(1) is missing in this checkout" >&2; exit 2; }

try:
	$(call need,demo/setup.sh,try)
	bash demo/setup.sh --attach

try-clean:
	$(call need,demo/teardown.sh,try-clean)
	bash demo/teardown.sh

# Frames show the plugin path, so they are rendered from $(RENDER_DIR) only:
# elsewhere the tracked and new files are copied there first, and docs/img back.
demos:
	$(call need,demo/render.sh,demos)
	@here=$$(pwd -P); \
	case $$here in \
	  $(RENDER_DIR) | /private$(RENDER_DIR)) bash demo/render.sh ;; \
	  *) \
	    if [ -e $(RENDER_DIR) ] && [ ! -e $(RENDER_DIR)/.make-demos-copy ]; then \
	      echo "make demos: $(RENDER_DIR) exists and is not a copy made by make demos; remove it first" >&2; \
	      exit 2; \
	    fi; \
	    mkdir -p $(RENDER_DIR) && touch $(RENDER_DIR)/.make-demos-copy && \
	    { git ls-files -z; git ls-files -z --others --exclude-standard; } | \
	      rsync -a --from0 --files-from=- ./ $(RENDER_DIR)/ && \
	    (cd $(RENDER_DIR) && bash demo/render.sh) && \
	    mkdir -p docs/img && rsync -a $(RENDER_DIR)/docs/img/ docs/img/ ;; \
	esac

scrub:
	scripts/scrub-check.sh --public
	@if [ -n "$$SCRUB_DENYLIST_FILE" ]; then scripts/scrub-check.sh --all; \
	else echo "make scrub: SCRUB_DENYLIST_FILE not set; private denylist skipped"; fi

docs-check:
	$(call need,scripts/check-docs.sh,docs-check)
	bash scripts/check-docs.sh
