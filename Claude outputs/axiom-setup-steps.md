# Getting Axiom Running on Hounddog

After Cursor finishes the code changes, here's what you do on the infrastructure side.

## 1. Create your Axiom account

Go to app.axiom.co and sign up. Free tier is 500GB/month, way more than we need.

## 2. Create two datasets

In the Axiom console, go to Settings, then Datasets, then New Dataset. Create two:

- **hounddog** for the backend app logs
- **birddog** for the enforcement device logs (BirdDog will use this later)

## 3. Create an API token

Settings, then API Tokens, then New Token. Name it something like `hounddog-ingest`. Give it Ingest and Query permissions, scoped to both datasets. Copy the token (starts with `xaat-`). You won't see it again.

While you're there, note your org ID. It's the slug in your Axiom URL, like `moravian-parking` from `moravian-parking.app.axiom.co`. You can also find it under Settings, then General.

## 4. Add env vars in Coolify

Open your Hounddog service in Coolify and add these environment variables (or add them to the `.env` file on the server, same thing):

```
AXIOM_TOKEN=xaat-your-token-here
AXIOM_ORG_ID=your-org-slug
```

That's it. `AXIOM_DATASET` and `AXIOM_DEVICE_DATASET` default to `hounddog` and `birddog` already, so you don't need to set those unless you named the datasets something different.

## 5. Redeploy

Redeploy the container from Coolify. On startup, `setup_logging()` sees the token and starts shipping logs.

## 6. Check that it's working

Hit a few pages on parking.moravian.edu, then go to Axiom, open the hounddog dataset, click the Stream tab. You should see JSON log events showing up with fields like `event`, `level`, `logger`, `request_id`, `user`, `method`, `path`.

If nothing shows up in Axiom, check the container's stdout logs in Coolify. structlog still writes everything to console regardless of whether Axiom is connected, so the app won't go silent either way. If you see JSON-formatted log lines in stdout but nothing in Axiom, double-check the token and org ID.

## Later: BirdDog

The `/api/device-logs` endpoint is already deployed and waiting. When we add the LogShipper to the BirdDog iOS app, device logs will start appearing in the `birddog` dataset automatically. Separate change, no rush.
