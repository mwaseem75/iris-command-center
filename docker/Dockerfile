# IRIS Command Center — IRIS image with the Embedded Python bonus modules,
# their pip dependencies, the docs corpus Ask IRIS indexes, and the ISOE
# ObjectScript classes staged for compilation. Everything is ready on first
# boot except a real OpenAI API key, which is never baked into an image —
# see docs/docker.md and docs/ask-iris.md.
#
# Build from the repository root: docker build -f docker/Dockerfile .
# (docker-compose.yml at the repo root does this for you.)
FROM intersystemsdc/iris-community:2026.2

USER root

# Work around a bug confirmed live in this base image's own entrypoint
# (/docker-entrypoint.sh, docker_setup_namespace): its irissqlcli-based
# "does the namespace already exist" check fails with "Cannot call an iris
# .package wrapper... dbapi.connect" on every first boot, crashing the
# container before it ever reaches /docker-entrypoint-initdb.d/. Reproduced
# on a completely unmodified, freshly-pulled copy of this exact image, so
# it is not something introduced by this Dockerfile. The check is also
# redundant for this project: the "USER" namespace it exists to create
# already ships mounted by IRIS itself before this step ever runs (visible
# in the boot log as "Mounted database /usr/irissys/mgr/user/"). See
# docs/docker.md for the full diagnosis.
RUN sed -i 's/^[[:space:]]*docker_setup_namespace[[:space:]]*$/\t: # patched out -- see docs\/docker.md/' /docker-entrypoint.sh

# Embedded Python modules (see iris/python/) — copied onto PYTHONPATH
# (already /usr/irissys/mgr/python per this image's own env var), plus the
# docs corpus Ask IRIS indexes, built straight from this repo's real docs
# rather than a duplicated copy, so it can never drift from docs/api-matrix.md.
COPY iris/python/health_analyzer.py /usr/irissys/mgr/python/health_analyzer.py
COPY iris/python/ask_iris.py /usr/irissys/mgr/python/ask_iris.py
COPY README.md /usr/irissys/mgr/python/docs-corpus/README.md
COPY docs/api-matrix.md /usr/irissys/mgr/python/docs-corpus/api-matrix.md
COPY docs/health-analyzer.md /usr/irissys/mgr/python/docs-corpus/health-analyzer.md
COPY docs/ask-iris.md /usr/irissys/mgr/python/docs-corpus/ask-iris.md
COPY docs/docker.md /usr/irissys/mgr/python/docs-corpus/docker.md
COPY docs/architecture.md /usr/irissys/mgr/python/docs-corpus/architecture.md
COPY docs/security.md /usr/irissys/mgr/python/docs-corpus/security.md

# ObjectScript classes, staged for install.sh (below) to compile on first boot.
COPY iris/classes/ISOE/ /opt/iris-command-center/classes/ISOE/

# Runs once, after IRIS's own first-boot init — see
# /docker-entrypoint.sh's docker_process_init_files and docs/docker.md.
COPY docker/install.sh /docker-entrypoint-initdb.d/install.sh
RUN chmod 755 /docker-entrypoint-initdb.d/install.sh

# psutil (HealthAnalyzer) and LangChain + the OpenAI integration (Ask IRIS)
# — neither ships in the base image. Installed as irisowner specifically:
# confirmed live that pip installs land in irisowner's own user site-packages
# (~/.local/lib/python3.12/site-packages), which is what Embedded Python
# actually reads at runtime — a root-context install would land somewhere
# Embedded Python never looks.
USER irisowner
RUN pip3 install --no-cache-dir --user psutil langchain langchain-openai langchain-community
