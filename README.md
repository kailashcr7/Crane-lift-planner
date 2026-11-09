# Lift planner – mobile and crawler cranes

A single-file lift plan tool for mobile and crawler cranes of any make: `public/index.html`, vanilla JS, no build step, no backend.
The screen is laid out like the document it produces – paper background, navy ink, numbered sections, IBM Plex type – and walks through six steps (Lift, Crane & chart, Site layout, Load & rigging, Checks, Document) with a results summary pinned under the header.
Plans and load charts are stored in the browser (`localStorage`, uploaded chart pages in IndexedDB); export and import them as JSON to move between devices.

## What it does

- **Lift** – details, people, permit, critical-lift factors, planner settings (critical threshold 75 % by default, minimum boom clearance, company and project on the printout).
- **Crane & chart** – the crane (any make and model, crawler or on outriggers) with the load chart for the configuration on site, boom length, pick and set radius, slew. The rating-book editor takes the chart page from the operator's manual or the commercial load chart as a PDF or photo (kept with the chart and printed as an appendix; a digital PDF's table text is read out to prefill the grid), a CSV/TSV file, or a pasted grid: first row the boom lengths, then one row per radius with the rated load in tonnes per boom length, `-` where the book shows none.
- **Site layout** – upload a photo, drone shot, drawing or 3D view of the lifting area (PDF, JPG, PNG; kept in IndexedDB) and mark it up: scale from a known distance, crane slew centre, pick and set points, obstacles with heights, exclusion zone, powerlines. Radii, slew and the nearest obstacle are measured from the markup, compared with the plan and can be applied to it; a load path outside the exclusion zone or inside the powerline no-go distance fails the plan. The marked-up image prints on the plan with the measured-versus-plan table.
- **Load & rigging** – load mass with an allowance for calculated or estimated weights, gear list with WLLs, sling legs and angle (four legs ⇒ two carry unless ticked).
- **Checks** – rated capacity is the chart value at the next tabulated radius at or beyond the working radius (no interpolation), worst of pick and set; gross load = load + allowance + gear + hook block (unless the chart includes it); utilisation at or above the threshold or any ticked factor ⇒ critical lift. Hook height and boom clearance over an obstacle use the chart's pivot geometry; ground bearing is crane + load over the track (or mat) area, doubled for one loaded track, or 75 % of crane + load on one outrigger pad (or its mat), against the allowable pressure entered.
- **AI assistant (optional)** – with your own Claude API key, entered in the planner settings and kept on this device: read a photographed load chart into the rating table, describe the lift scene and its hazards from the site image, or review the plan's figures. Each is a button that sends that data straight from the browser to api.anthropic.com with your key (structured JSON answers, server-side refusal fallbacks); the answers are drafts to check and copy into the plan, never a capacity or a verdict. The key is left out of JSON exports.
- **Plan document** – a two-page A4 lift plan (browser print → Save as PDF) with the site layout, a plan sketch with the load path and a to-scale elevation (base, superstructure, telescopic boom, hook block, rigging, load, set-down level and obstacle), the pre-lift checklist, a sign-off grid and the uploaded chart pages as an appendix.

## Load charts

The only chart shipped is a **fictitious demo**, clearly labelled, so the tool can be tried; any plan built on it prints a warning banner.
Enter the chart from the rating book for the machine and configuration on site (one chart per boom system, counterweight, track or outrigger setting and slew range).
The `SUGGEST` list carries indicative headline figures for a few common cranes (public sources) – it only adds a note and a sanity check; the rating book and the crane's load moment indicator govern.
PDF pages are rendered and read with a vendored copy of pdf.js (`public/vendor/pdfjs`).

## Run and test

```
python3 -m http.server -d public 8080      # then open http://localhost:8080
python3 tools/test/liftplan.py            # headless Chromium: arithmetic, chart editor and uploads, site markup, AI assistant against a mocked API, phone layout, PDF (needs playwright, pypdf, pdftoppm)
```

Deploy anywhere that serves static files; `netlify.toml` publishes `public/`.
