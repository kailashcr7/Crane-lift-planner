# Lift planner – Sennebogen cranes

A single-file lift plan tool for Sennebogen telescopic crawler cranes: `public/index.html`, vanilla JS, no build step, no backend.
The screen is laid out like the document it produces – paper background, navy ink, numbered sections, IBM Plex type – and walks through five steps (Lift, Crane & chart, Load & rigging, Checks, Document) with a results summary pinned under the header.
Plans and load charts are stored in the browser (`localStorage`); export and import them as JSON to move between devices.

## What it does

- **Lift** – details, people, permit, critical-lift factors, planner settings (critical threshold 75 % by default, minimum boom clearance, company and project on the printout).
- **Crane & chart** – Sennebogen model, the load chart for the configuration on site, boom length, pick and set radius, slew. The rating-book editor takes a pasted grid: first row the boom lengths, then one row per radius with the rated load in tonnes per boom length, `-` where the book shows none (tabs, commas or spaces).
- **Load & rigging** – load mass with an allowance for calculated or estimated weights, gear list with WLLs, sling legs and angle (four legs ⇒ two carry unless ticked).
- **Checks** – rated capacity is the chart value at the next tabulated radius at or beyond the working radius (no interpolation), worst of pick and set; gross load = load + allowance + gear + hook block (unless the chart includes it); utilisation at or above the threshold or any ticked factor ⇒ critical lift. Hook height and boom clearance over an obstacle use the chart's pivot geometry; ground bearing is crane + load over the track (or mat) area, doubled for one loaded track, against the allowable pressure entered.
- **Plan document** – a two-page A4 lift plan (browser print → Save as PDF) with plan and elevation sketches, the pre-lift checklist and a sign-off grid.

## Load charts

The only chart shipped is a **fictitious demo**, clearly labelled, so the tool can be tried; any plan built on it prints a warning banner.
Enter the chart from the rating book for the machine and configuration on site (one chart per boom system, counterweight, track width and slew range).
The `MODELS` list carries indicative headline figures only (public sources) – the rating book and the crane's load moment indicator govern.

## Run and test

```
python3 -m http.server -d public 8080      # then open http://localhost:8080
python3 tools/test/liftplan.py            # headless Chromium: arithmetic, chart editor, phone layout, PDF (needs playwright, pypdf, pdftoppm)
```

Deploy anywhere that serves static files; `netlify.toml` publishes `public/`.
