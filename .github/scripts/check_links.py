#!/usr/bin/env python3
"""Check every link on the site and report the ones that are really gone.

Run monthly by .github/workflows/link-check.yml. Writes link-report.md and exits
1 only when a link is dead, which makes the workflow open an issue. Hosts that
block robots, and one-off network trouble, are reported but do not fail the run,
so a monthly nag only arrives when something needs fixing.
"""
import concurrent.futures
import pathlib
import re
import subprocess
import sys

PAGES = ["index.html", "404.html"]
AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
         "(KHTML, like Gecko) Chrome/126 Safari/537.36")
CURL_DNS_FAILURE = 6  # host does not resolve: the link really is gone
GONE = {404, 410}
BLOCKED = {401, 403, 429}


def links():
    found = set()
    for page in PAGES:
        text = pathlib.Path(page).read_text()
        for url in re.findall(r'https?://[^\s"\'<>)]+', text):
            found.add(url.replace("&amp;", "&").rstrip(".,"))
    return sorted(found)


def check(url):
    """Return (url, http status, curl exit code), retrying once on a network hiccup."""
    status, exit_code = 0, 0
    for _ in range(3):
        result = subprocess.run(
            ["curl", "-sS", "-L", "-m", "30", "-A", AGENT, "-o", "/dev/null", "-w", "%{http_code}", url],
            capture_output=True, text=True, check=False)
        status, exit_code = int((result.stdout or "0").strip() or 0), result.returncode
        if 200 <= status < 300 or status in GONE or exit_code == CURL_DNS_FAILURE:
            break
    return url, status, exit_code


def verdict(status, exit_code):
    if 200 <= status < 300:
        return "ok"
    if status in GONE or exit_code == CURL_DNS_FAILURE:
        return "dead"
    if status in BLOCKED:
        return "blocked"
    return "unreachable"


def main():
    urls = links()
    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        results = sorted((url, status, verdict(status, exit_code))
                         for url, status, exit_code in pool.map(check, urls))
    group = lambda kind: [(url, status) for url, status, v in results if v == kind]
    dead, blocked, unreachable = group("dead"), group("blocked"), group("unreachable")

    report = [f"Checked {len(urls)} links on {', '.join(PAGES)}: "
              f"{len(group('ok'))} fine, {len(dead)} dead, {len(blocked)} blocked by the host, "
              f"{len(unreachable)} unreachable this run.", ""]
    if dead:
        report.append("**Dead links, worth fixing:**")
        report += [f"- `{status or 'host not found'}` {url}" for url, status in dead]
        report.append("")
    if blocked:
        report.append("Blocked to robots, so not checked. These still open in a browser:")
        report += [f"- `{status}` {url}" for url, status in blocked]
        report.append("")
    if unreachable:
        report.append("Did not answer this run. Usually a passing network problem, "
                      "but worth a look if the same link keeps appearing:")
        report += [f"- `{status or 'no response'}` {url}" for url, status in unreachable]
        report.append("")
    if not dead:
        report.append("No dead links.")
    pathlib.Path("link-report.md").write_text("\n".join(report) + "\n")
    print("\n".join(report))
    return 1 if dead else 0


if __name__ == "__main__":
    sys.exit(main())
