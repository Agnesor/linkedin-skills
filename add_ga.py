"""Insert the Google Analytics tag into Streamlit's index.html when GA_MEASUREMENT_ID is set.

Streamlit renders its own HTML shell, so the tag has to be patched into the installed
package. Without the environment variable nothing is changed, which keeps forks and local
runs from reporting to someone else's analytics property. Failures are logged and never
stop the app from starting.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

MARKER_ID = "google_analytics"
ID_PATTERN = re.compile(r"G-[A-Z0-9]{4,20}")
TAG = """<!-- Google tag (gtag.js) -->
<script async src="https://www.googletagmanager.com/gtag/js?id={id}"></script>
<script id="{marker}">
  window.dataLayer = window.dataLayer || [];
  function gtag(){{dataLayer.push(arguments);}}
  gtag('js', new Date());
  gtag('config', '{id}');
</script>
"""


def streamlit_index() -> Path:
    import streamlit

    return Path(streamlit.__file__).parent / "static" / "index.html"


def inject(index: Path, measurement_id: str | None) -> str:
    """Patch ``index`` and return one of: skipped, injected, already present."""
    if not measurement_id:
        return "skipped (GA_MEASUREMENT_ID not set)"
    if not ID_PATTERN.fullmatch(measurement_id):
        raise ValueError(f"invalid GA_MEASUREMENT_ID {measurement_id!r}")
    html = index.read_text(encoding="utf-8")
    if f'id="{MARKER_ID}"' in html:
        return "already present"
    if "<head>" not in html:
        raise ValueError(f"no <head> tag in {index}")
    tag = TAG.format(id=measurement_id, marker=MARKER_ID)
    index.write_text(html.replace("<head>", "<head>\n" + tag, 1), encoding="utf-8")
    return "injected"


def main() -> int:
    try:
        status = inject(streamlit_index(), os.environ.get("GA_MEASUREMENT_ID"))
    except (OSError, ValueError) as exc:
        print(f"add_ga: ERROR {exc}", file=sys.stderr)
        return 0
    print(f"add_ga: {status}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
