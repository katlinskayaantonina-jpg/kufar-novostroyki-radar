"""Check dashboard script syntax without running authenticated browser."""
from pathlib import Path
import subprocess
import tempfile

html = Path("worker/src/dashboard.html").read_text(encoding="utf-8")
assert html.count("<script>") == 1
source = html.split("<script>",1)[1].split("</script>",1)[0]
with tempfile.TemporaryDirectory() as tmp:
    file = Path(tmp)/"dashboard.js"
    file.write_text(source, encoding="utf-8")
    subprocess.run(["node", "--check", str(file)], check=True)
assert '["fast","Быстрый старт"]' in html
assert 'getJSON("fast").catch' in html
print("Dashboard JavaScript syntax and fast tab wiring: OK")
