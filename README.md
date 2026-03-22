# GAIA Magnetics — V2 UI Preview

**Terracode Analytics**

## Contents

```
gaia-magnetics/
├── frontend/
│   └── index.html        # Complete standalone UI — open directly in browser
└── README.md
```

## How to use

1. Open `frontend/index.html` directly in any modern browser (Chrome, Firefox, Edge, Safari)
2. No server, build step, or dependencies required — fully self-contained
3. Use the **⛶** button (top-right) for full screen
4. Use the **☀/☾** button (top-right) to toggle dark mode

## Screens

| Screen | Description |
|--------|-------------|
| Home | Platform overview, capabilities, about |
| Project Setup | Project context, basemap upload, survey data upload, column mapping, scenario, station spacing |
| Analysis | Corrections (incl. low-pass / high-pass filtering), prediction modelling, add-ons |
| Preview | Configuration summary, station map preview, Aurora AI pre-run analysis |
| Processing | Visual pipeline execution with step-by-step progress |
| Visualisation | Heatmap / Contour / 3D / Map overlay views with Aurora interpretation |
| Export | All 8 output formats, Aurora AI report options, delivery configuration |

## Tech stack (preview)

- HTML5 / CSS3 / Vanilla JS — no framework dependencies
- Google Fonts: Roboto, Manrope, JetBrains Mono
- Designed for production implementation in React + TailwindCSS

## Notes

- All form fields show placeholder state (no dummy data)
- Dark mode fully implemented — all components adapt
- Filtering checkbox reveals Low-pass / High-pass sub-selection
- Platform radio (Ground / Airborne) — mutually exclusive
- Scenario radio (Explicit / Sparse) — Explicit disables station spacing input
- Processing mode (Single / Multi-line) — Multi-line enables multiple file uploads

---
*GAIA Magnetics · Terracode Analytics · Confidential*
