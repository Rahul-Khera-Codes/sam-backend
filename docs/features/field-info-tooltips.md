# Field Info Tooltips (AIE-35)

## What it does
Replaces small gray helper-text captions under form fields (usually explaining which
agent/component consumes that field) with a small (i) info icon next to the field's label.
Hovering/clicking the icon shows the same text in a popup tooltip. Reduces page clutter and
the helper text renders at normal tooltip font size instead of `text-xs`.

## Key files (ai-employees-app)
- `src/components/ui/info-tooltip.tsx` — new reusable `InfoTooltip` component. Wraps the
  existing shadcn/Radix `Tooltip` primitives (`src/components/ui/tooltip.tsx`) with a
  `lucide-react` `Info` icon trigger. `TooltipProvider` is already mounted app-wide in
  `src/App.tsx`, so no extra setup is needed at call sites — just
  `<InfoTooltip>helper text</InfoTooltip>` next to a `<Label>`/heading.
- `src/pages/dashboard/BusinessSettings.tsx` — Company Logo caption, both employee
  check-in/payment code switches.
- `src/components/business/BrandingTab.tsx` — Color Palette note, Mission, Unique Value
  Claims, Extra Guidelines, Target Niche, Communication Strategy note, Competitive Analysis
  note, Key Differentiator. `TagListField` gained an optional `tooltip` prop for this.
- `src/components/business/DocumentsTab.tsx` — Document Name field.
- `src/components/business/ServicesTab.tsx` — On-site service switch.

## Scope decisions
- Only applied where a field/section had a real caption to convert (things like "Used by the
  HR Assistant (Ava)…" or "For your own reference — not currently used by any agent"). Section
  intro sentences that aren't per-field usage notes (e.g. "Configure how your brand
  communicates") were left visible as normal text.
- Skipped `IntegrationsTab.tsx` — its card description text is the primary content of each
  integration card, not a hideable caption.
- Skipped `TaxesSettingsTab.tsx` — no comparable per-field caption exists there today.
- Not yet applied to other settings pages that share the same label+helper-text idiom
  (`AccountSettings.tsx`, `GlobalSettings.tsx`, `CustomerServiceSettings.tsx`,
  `customer-service/AgentSettings.tsx`, `TaxesSettingsTab.tsx`). Linear AIE-35 named
  `/dashboard/settings/business` as the example page; rolling this out further is a natural
  follow-up but wasn't done in this pass.

## Linear
[AIE-35](https://linear.app/ai-employees-inc/issue/AIE-35/iae-add-tooltips-with-info-icons-to-fields)
