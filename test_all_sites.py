"""Quick smoke-test runner: load each configured site's signup + signin URL,
detect form, attempt fill, report per-site status. AI is left ON if available.

Usage:  python test_all_sites.py
Writes a Markdown report to test_report.md and prints a summary table.
"""

import asyncio
import logging
import os
import time

import sites
import platform_checker
from screenshotter import browser_pool

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("test_all_sites")

TEST_NUMBER = "15551234567"
PER_SITE_TIMEOUT = 90.0


def _row(s: dict) -> str:
    return (
        f"| {s['platform']} | {s['signup']} | {s['signin']} | "
        f"{s['fields']} | {s['submits']} | {s['flags']} | {s['note']} |"
    )


async def main():
    all_sites = sites.list_sites()
    only = os.environ.get("ONLY_SITES")
    if only:
        wanted = {x.strip().lower() for x in only.split(",") if x.strip()}
        all_sites = [s for s in all_sites if s["name"].lower() in wanted]
    logger.info(f"Loaded {len(all_sites)} sites — starting smoke test")
    pool = browser_pool
    await pool.get()  # warm browser

    rows: list[dict] = []
    for i, site in enumerate(all_sites, 1):
        name = site["name"]
        if not (site.get("signup_url") or site.get("signin_url")):
            rows.append({
                "platform": name, "signup": "—", "signin": "—",
                "fields": "0/0", "submits": "0",
                "flags": "skip",
                "note": "no URL configured",
            })
            logger.info(f"[{i}/{len(all_sites)}] {name}: skipped (no URL)")
            continue

        t0 = time.time()
        logger.info(f"[{i}/{len(all_sites)}] {name}: starting…")
        try:
            r = await asyncio.wait_for(
                platform_checker.check_platform(name, TEST_NUMBER),
                timeout=PER_SITE_TIMEOUT,
            )
            elapsed = time.time() - t0
            su_f = int(r.get("signup_fields_filled", 0))
            su_t = int(r.get("signup_fields_total", 0))
            si_f = int(r.get("signin_fields_filled", 0))
            si_t = int(r.get("signin_fields_total", 0))
            subs = int(bool(r.get("signup_submitted"))) + int(bool(r.get("signin_submitted")))
            flags = []
            if r.get("captcha_present"): flags.append("🤖CAPTCHA")
            if r.get("blocked"): flags.append("🚧BLOCKED")
            if not r.get("signup_form_found") and not r.get("signin_form_found"):
                flags.append("⚠️no-form")
            note = (r["signup_msg"] or r["signin_msg"] or "")[:120].replace("|", "/")
            rows.append({
                "platform": name,
                "signup": r["signup_status"],
                "signin": r["signin_status"],
                "fields": f"{su_f + si_f}/{su_t + si_t}",
                "submits": str(subs),
                "flags": ", ".join(flags) or "ok",
                "note": f"{note} ({elapsed:.1f}s)",
            })
            logger.info(
                f"[{i}/{len(all_sites)}] {name}: done in {elapsed:.1f}s — "
                f"signup={r['signup_status']} signin={r['signin_status']} "
                f"fields={su_f + si_f}/{su_t + si_t} submits={subs}"
            )
        except asyncio.TimeoutError:
            rows.append({
                "platform": name, "signup": "TIMEOUT", "signin": "TIMEOUT",
                "fields": "0/0", "submits": "0",
                "flags": "⏱️timeout",
                "note": f"exceeded {PER_SITE_TIMEOUT}s",
            })
            logger.warning(f"[{i}/{len(all_sites)}] {name}: TIMEOUT")
        except Exception as e:
            rows.append({
                "platform": name, "signup": "ERR", "signin": "ERR",
                "fields": "0/0", "submits": "0",
                "flags": "❌error",
                "note": f"{type(e).__name__}: {str(e)[:120]}",
            })
            logger.error(f"[{i}/{len(all_sites)}] {name}: ERROR {e}")

    # Build report
    header = (
        "# Phone Number Platform Checker — Site Smoke Test\n\n"
        f"Test number: `+{TEST_NUMBER}`  •  Sites tested: {len(rows)}\n\n"
        "| Site | Signup | Signin | Fields | Submits | Flags | Note |\n"
        "|------|--------|--------|--------|---------|-------|------|\n"
    )
    body = "\n".join(_row(r) for r in rows)
    report = header + body + "\n"
    with open("test_report.md", "w") as f:
        f.write(report)

    # Print compact table to stdout
    print("\n" + "=" * 90)
    print(f"{'SITE':<22} {'SIGNUP':<14} {'SIGNIN':<14} {'FIELDS':<10} {'SUB':<4} FLAGS")
    print("-" * 90)
    for r in rows:
        print(f"{r['platform'][:21]:<22} {str(r['signup'])[:13]:<14} "
              f"{str(r['signin'])[:13]:<14} {r['fields']:<10} {r['submits']:<4} {r['flags']}")
    print("=" * 90)
    print(f"\nFull report → test_report.md")
    await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
