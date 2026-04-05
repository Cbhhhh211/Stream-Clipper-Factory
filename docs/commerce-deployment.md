# Commerce Deployment

This project now supports a lightweight public checkout flow:

1. Marketing page -> `/buy/{product}`
2. Customer enters email and generates a Stripe Checkout session
3. A QR code is rendered from the Checkout URL
4. Stripe webhook marks the order as paid
5. The success page polls order status and redirects to a protected download URL

## Recommended stack

- Frontend + API: Render web service
- Payment: Stripe Checkout
- File delivery: Cloudflare R2 or any S3-compatible object store

## Required environment variables

Core checkout:

- `STRIPE_SECRET_KEY`
- `STRIPE_WEBHOOK_SECRET`
- `STRIPE_PRICE_ID_CREATOR`
- `STRIPE_PRICE_ID_STUDIO`

Digital delivery:

- `S3_ENDPOINT_URL`
- `S3_ACCESS_KEY`
- `S3_SECRET_KEY`
- `S3_BUCKET`
- `S3_REGION`
- `PUBLIC_PRODUCT_CREATOR_S3_KEY` or `PUBLIC_PRODUCT_CREATOR_DOWNLOAD_URL`
- `PUBLIC_PRODUCT_STUDIO_S3_KEY` or `PUBLIC_PRODUCT_STUDIO_DOWNLOAD_URL`

Optional marketing config:

- `PUBLIC_SITE_BRAND`
- `PUBLIC_CONTACT_EMAIL`
- `PUBLIC_BOOKING_URL`

## Stripe setup

1. Create one-time Prices for the Creator and Studio products.
2. Copy the Price IDs into:
   - `STRIPE_PRICE_ID_CREATOR`
   - `STRIPE_PRICE_ID_STUDIO`
3. Add a webhook endpoint:
   - `https://your-domain/api/v1/public/orders/webhooks/stripe`
4. Subscribe to these events:
   - `checkout.session.completed`
   - `checkout.session.async_payment_succeeded`
   - `checkout.session.async_payment_failed`
   - `checkout.session.expired`

## File delivery setup

1. Upload the final product zip to your object store.
2. Set the corresponding object key in:
   - `PUBLIC_PRODUCT_CREATOR_S3_KEY`
   - `PUBLIC_PRODUCT_STUDIO_S3_KEY`
3. The API will generate a temporary signed download URL after payment succeeds.

## Render notes

- Keep `API_MODE=lite` for the marketing + direct delivery setup.
- Persist `OUTPUT_DIR` using a Render disk if you want local order JSON files to survive restarts.
- If you prefer not to use a disk, move the order store to a database before launch.
