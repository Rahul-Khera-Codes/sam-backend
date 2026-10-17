# Product Management (AIE-103)

## What it does
A new **Product Management** page (Sidebar, between Customer List and Calendar, route `/dashboard/product-management`) where a business keeps a product catalog: name, description, price, category/subcategory, UPC barcode and a photo. Catalog items can then be added to an appointment's **Payment Details** as line items, next to the existing services.

## Page (`src/pages/dashboard/ProductManagement.tsx`)
- Stats row (product count, average price, category count), search (name / UPC / category), category filter, sortable columns (name, category, subcategory, price).
- **Add / edit product dialog** (`components/products/ProductDialog.tsx`): photo (upload, drag-drop, paste via button or Ctrl/⌘+V, copy, camera capture), name, description, price, category + subcategory with inline "add new", UPC with validation + barcode preview + camera scan.
- **UPC rules** (`lib/gtin.ts`): 8 / 12 / 13 / 14 digits, valid GTIN check digit, unique per business (enforced client-side for a friendly message and by a DB unique constraint).
- **Import / Export CSV**: export writes `name, description, price, category, subcategory, upc` (cells starting with `= + - @` are prefixed with `'` so spreadsheets don't run them as formulas). Import needs `name, price, upc`; shows a preview with per-row errors (missing name, bad price, invalid UPC, UPC already exists / duplicated inside the file) and imports only the valid rows. Photos are not part of CSV.
- Delete asks for confirmation; past payment records are unaffected (see below).

## Data model (migration `20261017120000_products_catalog.sql`, additive only)
- `product_categories` — `business_id`, `parent_id` (NULL = category, set = subcategory), `name`; case-insensitive unique name per parent.
- `products` — `business_id`, `name`, `description`, `price NUMERIC(10,2) >= 0`, `category_id`, `subcategory_id`, `upc` (CHECK 8 or 12–14 digits), `image_path`, `UNIQUE(business_id, upc)`.
- Storage bucket `product-images` (**public read**, object path `<business_id>/<product_id>.jpg`; writes restricted to members of that business's folder). Public because photos render in lists and the payment picker; names are UUIDs.
- RLS like `customers`: any business member can read/create/update; only a Super Admin can delete. Products are **per business** (shared across locations).
- Hook: `src/hooks/useProducts.ts` (direct Supabase, no backend REST layer — same precedent as `useCustomers`). Photos are resized client-side to max 600px JPEG before upload.

## Payment Details update (`components/appointments/PaymentDetailsDialog.tsx`, `AddPaymentItemPanel.tsx`)
- New **Add item or service** panel under the items table: **From catalog** (search by name/category/UPC) and **Custom** (type Service/Item, name, optional description, price). The panel only loads the catalog when opened.
- Adding the same catalog product again bumps its quantity. Every line now has a remove button.
- A catalog line stores a **price snapshot** (`product_id`, `kind`, `description` + price on the line). Editing or deleting the product later never rewrites an existing invoice.
- Tip percentage buttons, taxes, split payments, refunds and employee codes already existed and are unchanged (see `appointment-payments.md`).
- Backend: `AppointmentPaymentLineItem` (`backend/app/schemas/appointments.py`) gained optional `product_id`, `kind` (`Service`|`Item`), `description`; `_build_payment_snapshot` (`routers/appointments.py`) writes them only when present, so legacy line items keep their exact shape. No DB change — `line_items` is JSON.

## Decisions / open points for the client
- Page is visible to all roles (not in `RESTRICTED_PAGES`); delete is Super-Admin only via RLS. Easy to restrict if the client wants.
- Currency is shown as CAD, matching the Payment Details dialog.
- Packages added: `jsbarcode` (barcode preview), `@zxing/browser` + `@zxing/library` (camera scan; loaded on demand so it isn't in the main bundle; the browser's built-in BarcodeDetector isn't in Safari/Firefox). Camera features need HTTPS or localhost.
- Not done: per-location pricing, product stock/inventory, bulk photo import, Remi (voice/executive agent) awareness of the catalog.

Verified (2026-10-17): migration applied (dry-run showed only this migration pending); regenerated Supabase types; `tsc -p tsconfig.app.json` — no errors in the new/changed files (12 pre-existing errors elsewhere, unchanged); both Docker stacks rebuilt; `products` / `product_categories` reachable under RLS and bucket exists; backend accepts legacy and new line items, rejects an invalid `kind`, and legacy snapshots are byte-for-byte the same shape. Not yet verified in a browser: add/edit/delete a product, photo + camera + scan flows, CSV round-trip, adding catalog items in Payment Details.
