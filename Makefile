# RepoMind. Run `make setup` once, then `make check-02` whenever you like.

PY ?= .venv/bin/python

.PHONY: setup test ping reset check-02 bounds-smoke

setup:
	python3 -m venv .venv
	.venv/bin/pip install -q -r requirements.txt
	@echo "ready. Next: copy your Assignment 1 model into settings.yaml and its price line into pricing.yaml, set your key, then make ping."

test:            ## the harness's own tests; they spend no tokens
	$(PY) -m unittest discover -s tests -t .

ping:            ## two tiny calls: your key, your model, tool calling and its price line
	$(PY) -m harness.ping

reset:           ## archive tracker comments and start empty (before a measurement sweep)
	$(PY) -m harness.tracker reset

bounds-smoke:    ## the agent way against the model that never stops; free
	$(PY) run.py --way agent --backend never-stops --set dev --runs 1

check-02:        ## the Assignment 2 checker
	$(PY) checks/check_02.py
