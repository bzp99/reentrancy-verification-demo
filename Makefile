# Reentrancy verification demo.
#
# _Authored by Claude Code_ - 2026-09-12.
#
# The leading `-` on the runner lines is deliberate: one tool failing must not
# stop the others. merge.py turns a missing result into an `error` verdict.

.PHONY: all pull image verify render check demo serve fixture offline clean

SLITHER_IMAGE  := trailofbits/eth-security-toolbox:nightly
MYTHRIL_IMAGE  := mythril/myth:0.24.8
SOLC_IMAGE     := ethereum/solc:0.8.26
SMT_IMAGE      := vdemo/smtchecker:0.8.26

all: demo

pull:
	docker pull $(SLITHER_IMAGE)
	docker pull $(MYTHRIL_IMAGE)
	docker pull $(SOLC_IMAGE)

# solc ships no Horn solver, so CHC needs an image we build ourselves.
image:
	docker build -t $(SMT_IMAGE) docker/smtchecker/

verify:
	@mkdir -p out/raw out/normalized
	-python3 tools/run_slither.py
	-python3 tools/run_smtchecker.py
	-python3 tools/run_mythril.py
	python3 tools/merge.py

render:
	python3 tools/render.py

# The gate: fails when the fixed contract stops being provable, or when the
# vulnerable specimen stops being caught. Everything else is failure-tolerant.
check:
	python3 tools/check.py

demo: verify render
	@echo "open out/index.html"

serve: render
	python3 -m http.server 8000 --directory out

# Promote the current run as the committed fallback.
fixture:
	cp out/results.json fixtures/results.known-good.json
	@echo "fixtures/results.known-good.json updated - commit it"

clean:
	rm -rf out

# Offline rehearsal: same pipeline with the containers cut off the network.
# Proves nothing is quietly reaching for solc-bin.ethereum.org.
offline:
	DEMO_OFFLINE=1 $(MAKE) verify
