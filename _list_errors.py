import subprocess
result = subprocess.run(["python", "-m", "ruff", "check", "src", "--select", "N814,E501,E402,E701,N818,N806,N811,N817"], capture_output=True)
stdout = result.stdout.decode("utf-8", errors="replace")

lines = stdout.splitlines()
for i, line in enumerate(lines):
    stripped = line.strip()
    if any(code in stripped for code in ["N814 ", "E501 ", "E402 ", "E701 ", "N818 ", "N806 ", "N811 ", "N817 "]):
        # Find the file path above
        for j in range(i - 1, -1, -1):
            if not lines[j].startswith("  ") and not lines[j].startswith("     "):
                rel = lines[j].replace("d:\\oms-wms-tms\\", "").replace("\\", "/")
                print(f"[{rel}] {stripped}")
                break
        else:
            print(stripped)