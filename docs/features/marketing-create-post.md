# Marketing Employee: Create Post screen

## What it does
`ai-employees-app`'s Marketing Employee has three sidebar tabs, each its own route under
`/dashboard/marketing/*`: Create Post, Product Library, Post Calendar
(`src/components/layout/MarketingEmployeeLayout.tsx`, `src/App.tsx`). Create Post
(`src/pages/dashboard/marketing/MarketingCreatePost.tsx`) is a multi-step wizard (setup →
gallery → compose) for generating AI campaign concepts/images or turning a product-library
photo into a post, then scheduling or publishing it.

## State architecture (AIE-68 fix, 2026-09-07)
All of Create Post's in-progress form state (prompt, caption, selected platforms, generated
assets, layers, schedule date/time, product selection, drafts list, prompt templates, etc.) —
~30 fields — lives in `src/contexts/MarketingCreatePostContext.tsx`
(`MarketingCreatePostProvider` / `useMarketingCreatePostState`), **not** in local `useState`
inside `MarketingCreatePost`. The provider is mounted once in `MarketingEmployeeLayout`,
wrapping the `<Outlet />` that swaps between the three sibling routes.

**Why:** the three tabs are separate React Router routes, so switching tabs unmounts
`MarketingCreatePost` (and remounts it on return). Before this fix, all its state was local
`useState`, so navigating to Product Library or Post Calendar and back silently wiped
whatever the user had typed/generated/selected (AIE-68 bug report). Lifting the state to a
context provided above the `<Outlet />` means it survives the route swap — it only resets
when the user leaves the whole `/dashboard/marketing/*` section (layout unmounts) or after an
explicit action (e.g. generating a new campaign resets `assets`/`selectedConcept`/etc. inside
the relevant handler, same as before).

**How to apply:** any new Create Post form field must be added as `useState` inside
`MarketingCreatePostProvider` (not as local `useState` in `MarketingCreatePost.tsx`), or it
will silently regress this bug. Shared types (`MarketingStep`, `PostSource`,
`PreviewPlatform`, `MarketingDraft`, `PublishedPostLink`, `MarketingPromptTemplate`) and the
default-value constants (`defaultPrompt`, `defaultScheduleDate`, `defaultScheduleTime`) also
live in the context file now, imported into `MarketingCreatePost.tsx`, to avoid a circular
import between the two files.
