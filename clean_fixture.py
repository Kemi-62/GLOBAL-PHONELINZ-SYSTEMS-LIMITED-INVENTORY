import json
import sys
from pathlib import Path

EXCLUDE_MODELS = {
    "admin.logentry",
    "auth.permission",
    "auth.group",
    "contenttypes.contenttype",
}

DROP_FIELDS = {"groups", "user_permissions"}

def main(inp: str, out: str) -> None:
    data = json.loads(Path(inp).read_text(encoding="utf-8"))
    cleaned = []

    for obj in data:
        if obj.get("model") in EXCLUDE_MODELS:
            continue

        fields = obj.get("fields", {})
        for field in DROP_FIELDS:
            fields.pop(field, None)

        obj["fields"] = fields
        cleaned.append(obj)

    Path(out).write_text(json.dumps(cleaned, indent=2), encoding="utf-8")
    print(f"Saved cleaned fixture to {out}")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python clean_fixture.py input.json output.json")
        raise SystemExit(1)
    main(sys.argv[1], sys.argv[2])