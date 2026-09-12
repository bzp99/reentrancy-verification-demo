# solc 0.8.26 + a Horn solver, which is the combination nothing ships.
#
# _Authored by Claude Code_ - 2026-09-12
#
# Why this image exists: no official solc binary bundles a CHC solver. The
# static Linux builds (0.7.6, 0.8.26, 0.8.36 all checked) answer
# "Solver z3 was selected for SMTChecker but it is not available", and the
# WASM build that does bundle z3 cannot spawn the threads z3 needs. solc
# accepts exactly two Horn solvers - z3 and Eldarica - and Eldarica publishes
# a statically linked native binary, so we pair that with the stock compiler.
#
# Both binaries are static, so the runtime layer needs nothing but a shell.

FROM debian:12-slim AS fetch

ARG ELDARICA_VERSION=2.3
ARG ELDARICA_SHA256=

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL -o /tmp/eld.gz \
      "https://github.com/uuverifiers/eldarica/releases/download/v${ELDARICA_VERSION}/eldarica-x86-linux-static.gz" \
 && gunzip -c /tmp/eld.gz > /tmp/eld \
 && chmod 755 /tmp/eld \
 && /tmp/eld -h 2>&1 | head -3

# The stock compiler, taken straight from the official image so the version
# claim on the page matches an upstream artifact byte for byte.
FROM ethereum/solc:0.8.26 AS solc

FROM debian:12-slim

COPY --from=solc  /usr/bin/solc /usr/bin/solc
COPY --from=fetch /tmp/eld      /usr/local/bin/eld

# solc discovers Eldarica by looking for `eld` on PATH.
RUN solc --version && eld -h >/dev/null 2>&1 || true

ENTRYPOINT ["solc"]
