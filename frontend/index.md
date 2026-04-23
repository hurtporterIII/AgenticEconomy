---
title: Frontend index
system: agentic-economy-frontend
tags:
  - frontend
  - phaser
  - vite
  - dashboard
  - visualization
ai_summary: >-
  Phaser/Vite frontend for rendering agents, labels, counters, and narrative
  cards from backend API state. Most UI changes happen in src/game.js,
  src/scenes/MainScene.js, and src/ui/dashboard.js.
---

# frontend

## Core folders

- `src/scenes/` — Phaser scene logic (sprite movement/label rendering).
- `src/ui/` — dashboard, controls, overlays.
- `src/api/` — API client wrappers.
- `src/assets/` — sprites/images.

## High-value files

- `src/game.js` — app boot + sync/poll orchestration.
- `src/scenes/MainScene.js` — world/sprite state application.
- `src/ui/dashboard.js` — side-panel cards and event feed.
- `src/styles.css` — visual styling for cards/panels.
- `index.html` — Vite mount shell.
