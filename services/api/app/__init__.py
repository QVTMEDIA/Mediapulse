import sys
from pathlib import Path

# grp_calculator.py lives at the repo root, alongside app.py (the Streamlit
# app) — it has zero Streamlit dependency, so it's safe to import directly
# rather than duplicating its upload-parsing/GRP logic here (see
# app/parsing.py). This works identically in Docker and locally because it's
# computed from __file__, not CWD: services/api/Dockerfile preserves the
# same relative depth between this file and grp_calculator.py as the repo
# does, so parents[3] resolves to the repo root either way.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
