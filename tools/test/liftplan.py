#!/usr/bin/env python3
"""Drive the lift planner (public/index.html) end to end in headless Chromium.
Usage: python3 tools/test/liftplan.py [outdir]

Checks the demo-chart arithmetic (gross load, chart lookup at the next radius, utilisation, classification,
hook height, ground bearing), adds a chart through the rating-book editor (tab-separated with blank cells),
prints the plan document to PDF and checks it with pypdf, and screenshots every tab at phone width.
Exits non-zero on any JS error or failed check."""
import asyncio, sys, pathlib, subprocess, math, re
from playwright.async_api import async_playwright
ROOT = pathlib.Path(__file__).resolve().parents[2]  # project root
OUT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "tools/test/out"); OUT.mkdir(parents=True, exist_ok=True)
PORT = 8792
LAYOUT = """(()=>{const de=document.documentElement,out=[...document.querySelectorAll('#app input,#app select,#app textarea')].filter(e=>!['hidden','checkbox','radio','file'].includes(e.type)&&parseFloat(getComputedStyle(e).fontSize)<16).map(e=>'field under 16px: '+(e.dataset.k||e.dataset.c||e.id||e.className));
  if(de.scrollWidth>de.clientWidth)out.push('page wider than screen by '+(de.scrollWidth-de.clientWidth)+'px');return out})()"""

async def fits(pg, name):
    bad = await pg.evaluate(LAYOUT)
    assert not bad, f"{name} won't fit a phone screen: {bad}"

async def set_field(pg, key, value):
    sel = f'[data-k="{key}"]'
    tag = await pg.eval_on_selector(sel, "e=>e.tagName")
    if tag == "SELECT":
        await pg.select_option(sel, str(value))
    else:
        await pg.fill(sel, str(value))
    await pg.dispatch_event(sel, "input")
    await pg.wait_for_timeout(80)

async def strip(pg):
    t = await pg.inner_text("#strip")
    return re.sub(r"\s+", " ", t).lower()   # inner_text applies the CSS uppercase

async def main():
    srv = subprocess.Popen([sys.executable, "-m", "http.server", str(PORT), "-d", str(ROOT / "public")], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        async with async_playwright() as p:
            br = await p.chromium.launch()
            ctx = await br.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=1)
            pg = await ctx.new_page()
            errors = []
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.on("console", lambda m: errors.append(m.text) if m.type == "error" and "favicon" not in m.text else None)
            await pg.goto(f"http://localhost:{PORT}/index.html"); await pg.wait_for_timeout(400)

            # default plan on the demo chart: 13.5 m boom, pick 8 m / set 10 m, 5 t load + 10 % + gear + hook
            s = await strip(pg); print("strip:", s)
            assert "6.40 t" in s and "36.00 t" in s and "18%" in s and "standard lift" in s, s
            await set_field(pg, "title", "Test lift – precast panel")
            await fits(pg, "lift tab"); await pg.screenshot(path=OUT / "lp-01-lift.png", full_page=True)

            # crane tab: 42 m boom at 30 m set radius -> 4.4 t rating, overloaded
            await pg.click('[data-tab="crane"]'); await pg.wait_for_timeout(200)
            await set_field(pg, "boom", "42"); await set_field(pg, "setR", "30")
            s = await strip(pg); assert "4.40 t" in s and "145%" in s and "not ok" in s, s
            assert await pg.locator("tr.hit").count() >= 1
            await fits(pg, "crane tab"); await pg.screenshot(path=OUT / "lp-02-crane.png", full_page=True)

            # load tab: drop the load to 2.3 t -> gross 3.43 t (2.3 + 10 % + 0.10 gear + 0.8 hook), 78 % => critical
            await pg.click('[data-tab="load"]'); await pg.wait_for_timeout(200)
            await set_field(pg, "loadMass", "2.3")
            s = await strip(pg); assert "3.43 t" in s and "78%" in s and "critical lift" in s, s
            txt = await pg.inner_text("#body")
            # sling tension: 2.63 t below hook / 2 legs / cos 45° = 1.86 t
            assert "1.86" in txt, txt[:400]
            await pg.click("#rigAdd"); await pg.wait_for_timeout(100)
            assert await pg.locator(".rig-row").count() == 3
            await pg.click('[data-rigdel="2"]'); await pg.wait_for_timeout(100)
            assert await pg.locator(".rig-row").count() == 2
            await fits(pg, "load tab"); await pg.screenshot(path=OUT / "lp-03-load.png", full_page=True)

            # checks tab: hook height and ground bearing on the demo geometry
            await pg.click('[data-tab="check"]'); await pg.wait_for_timeout(200)
            await set_field(pg, "bearing", "150")
            txt = await pg.inner_text("#body")
            tip = 2.2 + math.sqrt(42**2 - 29**2)            # pivot 2.2 m, offset 1.0 m, 42 m boom at 30 m
            assert f"{tip:.1f}" in txt and f"{tip-2.0:.1f}" in txt, (tip, txt[:600])
            one_track = (92 + 3.43) * 9.81 / (2 * 7.6 * 0.9) * 2
            assert f"{one_track:.0f}" in txt, (one_track, txt)
            assert "EXCEEDS" not in txt and "✕" not in txt, txt
            # an obstacle the boom clips -> a fail
            await set_field(pg, "obstD", "20"); await set_field(pg, "obstH", "25")
            txt = await pg.inner_text("#body"); assert "Boom passes" in txt and "✕" in txt, txt
            await set_field(pg, "obstH", "10")
            txt = await pg.inner_text("#body"); assert "✕" not in txt, txt
            await pg.check('[data-check="weight"]'); await pg.check('[data-check="comms"]')
            await fits(pg, "checks tab"); await pg.screenshot(path=OUT / "lp-04-check.png", full_page=True)

            # rating-book editor: tab-separated grid with a blank cell must keep its columns
            await pg.click('[data-tab="crane"]'); await pg.wait_for_timeout(200)
            await pg.click("#openEditor"); await pg.wait_for_timeout(150)
            await pg.fill('[data-c="name"]', "683 E test chart"); await pg.dispatch_event('[data-c="name"]', "input")
            await pg.fill('[data-c="pivotH"]', "2.3"); await pg.dispatch_event('[data-c="pivotH"]', "input")
            grid = "Radius\t24\t30\n6\t40\t\n8\t\t28\n10\t30\t24\n12\t-\t20"
            await pg.fill('[data-c="grid"]', grid); await pg.dispatch_event('[data-c="grid"]', "input")
            await pg.click("#saveChart"); await pg.wait_for_timeout(250)
            assert "683 E test chart" in await pg.inner_text("#body")
            cells = await pg.eval_on_selector_all(".tablewrap tbody tr", "rows=>rows.map(r=>[...r.children].map(c=>c.textContent.trim()))")
            assert cells[1] == ["8.0 m", "–", "28.0"], cells
            assert cells[3][1] == "–" and cells[3][2] == "20.0", cells
            # pick 8 m on the 24 m boom -> next rated radius is 10 m at 30 t
            await set_field(pg, "boom", "24"); await set_field(pg, "pickR", "8"); await set_field(pg, "setR", "7")
            s = await strip(pg); assert "30.00 t" in s and "10.0 m" in s, s
            await pg.screenshot(path=OUT / "lp-05-chart.png", full_page=True)
            charts = await pg.evaluate("JSON.parse(localStorage.getItem('lp.charts')).length"); assert charts == 2

            # plan document: back on the demo chart (banner), print to PDF
            await set_field(pg, "chartId", "demo"); await set_field(pg, "boom", "42"); await set_field(pg, "setR", "30")
            await pg.click('[data-tab="doc"]'); await pg.wait_for_timeout(300)
            sheet = await pg.inner_text("#sheet")
            assert "CRITICAL LIFT" in sheet and "DEMO CHART" in sheet and "Test lift – precast panel" in sheet, sheet[:500]
            await pg.screenshot(path=OUT / "lp-06-doc.png", full_page=True)
            pdf = OUT / "lp-plan.pdf"
            await pg.emulate_media(media="print")
            await pg.pdf(path=pdf, format="A4", print_background=True, margin={"top": "12mm", "bottom": "12mm", "left": "12mm", "right": "12mm"})
            await pg.emulate_media(media="screen")
            from pypdf import PdfReader
            rd = PdfReader(str(pdf)); n = len(rd.pages)
            text = "\n".join(pg_.extract_text() or "" for pg_ in rd.pages)
            assert 2 <= n <= 3, f"{n} pages"
            w, h = float(rd.pages[0].mediabox.width), float(rd.pages[0].mediabox.height)
            assert abs(w - 595.28) < 2 and abs(h - 841.89) < 2, (w, h)
            for key in ["CRITICAL LIFT", "Capacity check", "Sign-off", "DEMO CHART", "Test lift"]:
                assert key.lower() in text.lower(), f"'{key}' missing from the PDF text"
            print(f"pdf: {n} pages, {pdf.stat().st_size//1024} KB")
            for f in OUT.glob("lp-plan-*.png"): f.unlink()
            subprocess.run(["pdftoppm", "-png", "-r", "60", str(pdf), str(OUT / "lp-plan")], check=False)

            # plans persist across a reload; duplicate and delete
            await pg.reload(); await pg.wait_for_timeout(400)
            assert "Test lift – precast panel" in await pg.inner_text("#planTitle")
            await pg.click("#dupPlan"); await pg.wait_for_timeout(150)
            assert await pg.locator("#planSel option").count() == 2
            pg.on("dialog", lambda d: asyncio.ensure_future(d.accept()))
            await pg.click("#delPlan"); await pg.wait_for_timeout(200)
            assert await pg.locator("#planSel option").count() == 1

            assert not errors, errors
            await br.close()
    finally:
        srv.terminate()
    print("lift planner OK – screenshots in", OUT)

asyncio.run(main())
