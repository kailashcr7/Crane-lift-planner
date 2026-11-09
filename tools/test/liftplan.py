#!/usr/bin/env python3
"""Drive the lift planner (public/index.html) end to end in headless Chromium.
Usage: python3 tools/test/liftplan.py [outdir]

Checks the demo-chart arithmetic (gross load, chart lookup at the next radius, utilisation, classification,
hook height, ground bearing), adds a crane and chart through the rating-book editor (page uploaded as an image,
table imported from CSV with blank cells, printed appendix, outrigger pad pressure, pages kept across a reload),
prints the plan document to PDF and checks it with pypdf, and screenshots every step at phone width.
Exits non-zero on any JS error or failed check."""
import asyncio, sys, pathlib, subprocess, math, re, base64, json
from playwright.async_api import async_playwright
ROOT = pathlib.Path(__file__).resolve().parents[2]  # project root
OUT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "tools/test/out"); OUT.mkdir(parents=True, exist_ok=True)
PORT = 8792
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")  # 1×1 px
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

            # rating-book editor: any make and model, a chart page uploaded as an image, the table from a CSV
            # file in which a blank cell must keep its column
            await pg.click('[data-tab="crane"]'); await pg.wait_for_timeout(200)
            await pg.click("#openEditor"); await pg.wait_for_timeout(150)
            for key, val in [("make", "Sennebogen"), ("model", "683 E"), ("name", "683 E test chart"), ("pivotH", "2.3")]:
                await pg.fill(f'[data-c="{key}"]', val); await pg.dispatch_event(f'[data-c="{key}"]', "input")
            await pg.set_input_files("#chartFiles", {"name": "chart-page.png", "mimeType": "image/png", "buffer": PNG})
            await pg.wait_for_selector(".pages img", timeout=10000)
            assert await pg.locator(".pages img").count() == 1
            csv = "Radius,24,30\n6,40,\n8,,28\n10,30,24\n12,-,20\n"
            await pg.set_input_files("#gridFile", {"name": "grid.csv", "mimeType": "text/csv", "buffer": csv.encode()})
            await pg.wait_for_timeout(300)
            assert (await pg.input_value('[data-c="grid"]')).startswith("Radius\t24\t30\n6\t40\t\n8\t\t28"), await pg.input_value('[data-c="grid"]')
            await pg.click("#saveChart"); await pg.wait_for_timeout(250)
            body = await pg.inner_text("#body"); assert "683 E test chart" in body and "Sennebogen 683 E" in body, body[:300]
            assert await pg.locator(".pages img").count() == 1   # shown with the rating table
            cells = await pg.eval_on_selector_all(".tablewrap tbody tr", "rows=>rows.map(r=>[...r.children].map(c=>c.textContent.trim()))")
            assert cells[1] == ["8.0 m", "–", "28.0"], cells
            assert cells[3][1] == "–" and cells[3][2] == "20.0", cells
            # pick 8 m on the 24 m boom -> next rated radius is 10 m at 30 t
            await set_field(pg, "boom", "24"); await set_field(pg, "pickR", "8"); await set_field(pg, "setR", "7")
            s = await strip(pg); assert "30.00 t" in s and "10.0 m" in s, s
            await pg.screenshot(path=OUT / "lp-05-chart.png", full_page=True)
            charts = await pg.evaluate("JSON.parse(localStorage.getItem('lp.charts')).length"); assert charts == 2

            # the uploaded page prints as an appendix to the plan built on this chart
            await pg.click('[data-tab="doc"]'); await pg.wait_for_timeout(300)
            sheet = await pg.inner_text("#sheet")
            assert "Appendix" in sheet and await pg.locator("#sheet img.attach").count() == 1, sheet[-400:]

            # the same crane on outriggers: 75 % of crane + load on one 0.6 x 0.6 m pad
            await pg.click('[data-tab="crane"]'); await pg.wait_for_timeout(200)
            await pg.click("[data-editchart]"); await pg.wait_for_timeout(150)
            await pg.select_option('[data-c="type"]', "outrigger"); await pg.dispatch_event('[data-c="type"]', "input"); await pg.wait_for_timeout(150)
            for key, val in [("padL", "0.6"), ("padW", "0.6"), ("opWeight", "60")]:
                await pg.fill(f'[data-c="{key}"]', val); await pg.dispatch_event(f'[data-c="{key}"]', "input")
            await pg.click("#saveChart"); await pg.wait_for_timeout(250)
            assert "outriggers" in (await pg.inner_text("#body")).lower()
            await pg.click('[data-tab="check"]'); await pg.wait_for_timeout(200)
            txt = await pg.inner_text("#body")
            pad = 0.75 * (60 + 2.3 * 1.1 + 0.10) * 9.81 / 0.36          # no hook block mass on this chart
            assert f"{pad:,.0f}" in txt and "one outrigger pad" in txt, (pad, txt[:900])
            await pg.screenshot(path=OUT / "lp-05b-outrigger.png", full_page=True)

            # site layout: upload an image, set the scale, place the crane, pick, set and an obstacle, apply
            await pg.click('[data-tab="site"]'); await pg.wait_for_timeout(200)
            photo = await pg.screenshot(clip={"x": 0, "y": 0, "width": 390, "height": 260})   # any PNG stands in for the site photo
            await pg.set_input_files("#siteFile", {"name": "site.png", "mimeType": "image/png", "buffer": photo})
            await pg.wait_for_selector("#site img", timeout=10000); await pg.wait_for_timeout(200)
            async def tap(tool, fx, fy):
                if tool: await pg.click(f'[data-tool="{tool}"]'); await pg.wait_for_timeout(80)
                await pg.evaluate("document.querySelector('#site').scrollIntoView({block:'center'})"); await pg.wait_for_timeout(50)
                b = await pg.locator("#site").bounding_box()
                await pg.mouse.click(b["x"] + fx * b["width"], b["y"] + fy * b["height"]); await pg.wait_for_timeout(150)
                return b
            await tap("scale", 0.1, 0.5); await tap(None, 0.6, 0.5)            # half the width = 10 m
            await pg.fill("#scaleM", "10"); await pg.click("#scaleSet"); await pg.wait_for_timeout(150)
            b = await tap("crane", 0.5, 0.5)
            await tap("pick", 0.7, 0.5)                                         # 0.2 w = 4 m
            await tap("set", 0.5, 0.5 - 0.25 * b["width"] / b["height"])       # 0.25 w = 5 m, 90° round
            await tap("obst", 0.6, 0.5)                                         # 2 m from the crane
            await pg.fill('[data-obsth="0"]', "2"); await pg.dispatch_event('[data-obsth="0"]', "input"); await pg.wait_for_timeout(150)
            txt = await pg.inner_text("#body")
            for key in ["4.0 m", "5.0 m", "90°", "2.0 m high at 2.0 m", "differs"]: assert key in txt, (key, txt[-900:])
            await fits(pg, "site tab"); await pg.screenshot(path=OUT / "lp-05c-site.png", full_page=True)
            await pg.click("#applySite"); await pg.wait_for_timeout(200)
            s = await strip(pg); assert "40.00 t" in s and "6.0 m" in s, s      # set 5 m -> next rated radius 6 m on the 24 m boom
            txt = await pg.inner_text("#body"); assert "differs" not in txt and txt.count("matches") >= 3, txt[-600:]

            # AI assistant with the planner's own key: the Messages API is mocked, the request shape and the
            # way answers land in the plan are what is checked
            calls = []
            async def fake_api(route):
                body = json.loads(route.request.post_data); calls.append((route.request.headers, body))
                props = body["output_config"]["format"]["schema"]["properties"]
                if "booms" in props: data = {"booms": [24, 30], "rows": [{"radius": 6, "caps": [40, None]}, {"radius": 8, "caps": [None, 28]}], "notes": ["capacities in t"]}
                elif "summary" in props: data = {"summary": "Open yard beside an excavation.", "hazards": [{"hazard": "Edge of excavation 3 m from the tracks", "control": "Keep the crane back at least the depth of the excavation"}], "verify": ["Depth of the excavation"]}
                elif "verdict" in props: data = {"verdict": "needs_changes", "findings": [{"severity": "high", "finding": "Utilisation 78% on a demo chart", "action": "Enter the rating book chart"}], "missing": ["Ground bearing from the geotech"]}
                else: data = {"ok": True}
                await route.fulfill(status=200, content_type="application/json", body=json.dumps({"id": "msg_test", "type": "message", "model": body["model"], "stop_reason": "end_turn",
                    "content": [{"type": "text", "text": json.dumps(data)}], "usage": {"input_tokens": 1, "output_tokens": 1}}))
            await pg.route("https://api.anthropic.com/**", fake_api)
            await pg.click('[data-tab="lift"]'); await pg.wait_for_timeout(200)
            assert await pg.locator("#aiTest").is_disabled()                      # no key, nothing can be sent
            await pg.fill('[data-ai="key"]', "sk-ant-test-key"); await pg.dispatch_event('[data-ai="key"]', "input")
            await pg.click("#aiTest"); await pg.wait_for_timeout(400)
            h, b = calls[-1]
            assert h["x-api-key"] == "sk-ant-test-key" and h["anthropic-version"] == "2026-10-21" and h["anthropic-dangerous-direct-browser-access"] == "true", h
            assert b["model"] == "claude-opus-5-5" and b["fallbacks"] == "default" and b["output_config"]["format"]["type"] == "json_schema", b
            await fits(pg, "lift tab with AI settings")
            # a photographed chart read into the rating table
            await pg.click('[data-tab="crane"]'); await pg.wait_for_timeout(200)
            await pg.click("[data-editchart]"); await pg.wait_for_timeout(150)
            await pg.click("#aiChart"); await pg.wait_for_selector("#useExtracted", timeout=5000)
            assert any(x.get("type") == "image" for x in calls[-1][1]["messages"][0]["content"]), "chart page not sent as an image"
            await pg.click("#useExtracted"); await pg.wait_for_timeout(150)
            assert await pg.input_value('[data-c="grid"]') == "Radius\t24\t30\n6\t40\t-\n8\t-\t28", await pg.input_value('[data-c="grid"]')
            await pg.click("#cancelChart"); await pg.wait_for_timeout(150)
            # the lift scene from the site image, added to the hazards
            await pg.click('[data-tab="site"]'); await pg.wait_for_timeout(200)
            await pg.click("#aiSite"); await pg.wait_for_selector("#aiSiteApply", timeout=5000)
            assert "Open yard beside an excavation." in await pg.inner_text("#body")
            await pg.click("#aiSiteApply"); await pg.wait_for_timeout(150)
            await pg.click('[data-tab="lift"]'); await pg.wait_for_timeout(200)
            assert "Edge of excavation 3 m from the tracks – Keep the crane back" in await pg.input_value('[data-k="hazards"]')
            # the plan review, added to the notes
            await pg.click('[data-tab="check"]'); await pg.wait_for_timeout(200)
            await pg.click("#aiReview"); await pg.wait_for_selector("#aiReviewApply", timeout=5000)
            txt = (await pg.inner_text("#body")).lower(); assert "needs changes" in txt and "utilisation 78% on a demo chart" in txt, txt[:1200]
            assert calls[-1][1]["output_config"]["effort"] == "high" and "gross_t" in calls[-1][1]["messages"][0]["content"][0]["text"]
            await pg.click("#aiReviewApply"); await pg.wait_for_timeout(150)
            assert "Review notes: [high] Utilisation 78%" in await pg.input_value('[data-k="notes"]')
            await pg.screenshot(path=OUT / "lp-05d-ai.png", full_page=True)
            await pg.unroute("https://api.anthropic.com/**")

            # plan document: back on the demo chart (banner), print to PDF
            await pg.click('[data-tab="crane"]'); await pg.wait_for_timeout(200)
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
            assert 2 <= n <= 4, f"{n} pages"
            w, h = float(rd.pages[0].mediabox.width), float(rd.pages[0].mediabox.height)
            assert abs(w - 595.28) < 2 and abs(h - 841.89) < 2, (w, h)
            for key in ["CRITICAL LIFT", "Capacity check", "Site layout", "Sign-off", "DEMO CHART", "Test lift"]:
                assert key.lower() in text.lower(), f"'{key}' missing from the PDF text"
            print(f"pdf: {n} pages, {pdf.stat().st_size//1024} KB")
            for f in OUT.glob("lp-plan-*.png"): f.unlink()
            subprocess.run(["pdftoppm", "-png", "-r", "60", str(pdf), str(OUT / "lp-plan")], check=False)

            # plans and uploaded pages persist across a reload; duplicate and delete
            await pg.reload(); await pg.wait_for_timeout(600)
            assert "Test lift – precast panel" in await pg.inner_text("#planTitle")
            assert await pg.evaluate("Object.values(S.attach).flat().length") == 1
            assert await pg.evaluate("Object.keys(S.site).length") == 1
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
