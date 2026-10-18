"""Keep engine errors visible; classify known environment-only messages separately."""

import re

ANSI = re.compile(r"\x1b\[[0-9;]*m")


def classify(text: str) -> dict:
    lines = ANSI.sub("", text).splitlines()
    errors, warnings = [], []
    for line in lines:
        if "Failed to read the root certificate store" in line:
            warnings.append(line)
        elif any(marker in line for marker in ("SCRIPT ERROR:", "ERROR:", "Parse Error:")):
            errors.append(line)
        elif "WARNING:" in line:
            warnings.append(line)
    return {"errors": errors, "warnings": warnings, "log": "\n".join(lines)}
