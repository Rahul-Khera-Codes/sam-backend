# Spec — Executive Agent WS4: Phase-1 central animated avatar

**Date:** 2026-06-25 · **Workstream:** WS4 · **Repo:** `ai-employees-app`
**Approved scope:** overview doc Phase 1 = clean animated avatar, 3 states; Phase 2 = HeyGen talking face (swap later).

## Verified current state
- Hook `useExecutiveSession` exposes `agentState: idle|listening|thinking|speaking` + `isConnected`.
- `AgentStatusHeader` already has small glyphs (mic-ping / thinking-dots / waveform). Center pane (`AgentDisplay`) has **no avatar** — empty state shows a static 💼 box; connected view shows only text.
- Tailwind keyframes available: `thinking-dot`, `waveform`, `pulse-slow` (+ built-in `ping`, `spin`).

## Build
- **New `AgentAvatar.tsx`** — a single orb reacting to state:
  - **not connected:** muted orb, 💼 inner glyph (preserve brand presence).
  - **idle (connected):** accent-gradient orb, slow `breathe`.
  - **listening:** concentric `ping` ripples around the orb (receiving).
  - **thinking:** slow rotating conic-gradient ring (`spin`).
  - **speaking:** 5 `waveform` bars inside the orb + faster pulse.
  - Self-contained + swappable: props are just `{agentState, isConnected}`; Phase 2 replaces the orb internals with a HeyGen `<video>` without touching callers. Mark the swap point in a comment.
- **Tailwind:** add one keyframe `breathe` (scale 1→1.06) + animation.
- **Wire into `AgentDisplay`:** render `<AgentAvatar>` centered above the message in the connected view, and replace the static 💼 in the empty state. Keep existing copy/text fallbacks.
- `aria-hidden` on the decorative orb; state is already announced textually in the header.

## Out of scope
HeyGen integration (Phase 2), avatar picker gallery, mood→expression mapping.

## Verify
- `tsc --noEmit` clean. Visually: connect → orb breathes; mic on → ripples; tool running → spin ring; Remi talking → waveform. Disconnect → muted 💼 orb. No layout shift / horizontal scroll.
