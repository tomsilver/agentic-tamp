# Sandbox image for agentic-tamp.
#
# Extends robocode-sandbox (Claude CLI + network firewall + write-restricted
# /sandbox) with a TAMPEST install and an in-container `check_move` tool, so the
# agent's `tool` mode can test motion feasibility while planning. The TAMPEST
# install also brings Pillow/numpy, so the agent can inspect the occupancy map
# precisely in either mode.
FROM robocode-sandbox

USER root

# Isolated venv for TAMPEST so it never collides with robocode's /robocode/.venv.
RUN python3.11 -m venv /opt/tamp-venv \
    && /opt/tamp-venv/bin/pip install --no-cache-dir --upgrade pip setuptools wheel

RUN /opt/tamp-venv/bin/pip install --no-cache-dir --pre unified-planning

# Install TAMPEST's dependencies explicitly. tampest pins python-fcl==0.7.0.8,
# which has no linux/aarch64 wheel; 0.7.0.11 (same 0.7.0 line) does, so we bump
# it and install tampest itself with --no-deps to bypass the exact pin.
RUN /opt/tamp-venv/bin/pip install --no-cache-dir \
        numpy==1.26.1 \
        shapely==2.0.7 \
        trimesh==4.6.6 \
        Pillow==10.2.0 \
        pyyaml==6.0.1 \
        opencv-python-headless==4.11.0.86 \
        pycollada==0.9 \
        python-fcl==0.7.0.11 \
        alphashape==1.3.1 \
        ompl==1.7.0 \
        z3-solver==4.15.0 \
        "pysmt @ git+https://github.com/pysmt/pysmt.git" \
        "tempest @ git+https://github.com/fbk-pso/tempest.git"

RUN /opt/tamp-venv/bin/pip install --no-cache-dir --no-deps \
        "tampest @ git+https://github.com/fbk-pso/tampest.git"

# The numbered doors/maze maps are .gitignored, so get_problem regenerates them
# at runtime into the benchmarks config dirs. Make those writable by `node`.
RUN chmod -R a+w /opt/tamp-venv/lib/python3.11/site-packages/benchmarks

# The feasibility tool and a wrapper on PATH (`check_move <from> <to> ...`).
RUN mkdir -p /opt/feasibility
COPY check_move.py /opt/feasibility/check_move.py
RUN printf '#!/bin/bash\nexec /opt/tamp-venv/bin/python /opt/feasibility/check_move.py "$@"\n' \
        > /usr/local/bin/check_move \
    && chmod +x /usr/local/bin/check_move

USER node
