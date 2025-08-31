import ast
import re

def load_molecule(filepath):
    keys = ["atom", "basis", "symmetry", "spin_sq", "charge", "n_frozen"]
    data = {}
    with open(filepath, "r") as f:
        lines = f.read()
    for key in keys:
        if key in lines:
            try:
                pattern = rf"{key}\s*=\s*(.*?)(?=\n\w+\s*=|\Z)"
                match = re.search(pattern, lines, re.DOTALL)
                if match:
                    value_str = match.group(1).strip()
                    data[key] = ast.literal_eval(value_str)
            except Exception:
                pass
    return (
        data.get("atom"),
        data.get("basis", "sto-3g"),
        data.get("symmetry", False),
        data.get("spin_sq", 0),
        data.get("charge", 0),
        data.get("n_frozen", None)
    )

