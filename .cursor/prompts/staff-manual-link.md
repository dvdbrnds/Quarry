# Add Staff Manual Link to Admin Navigation

## Context

The parking office staff manual PDF lives at `frontend/public/docs/staff-manual.pdf`. Vite serves `public/` files at the site root, so the live URL is `parking.moravian.edu/docs/staff-manual.pdf`. This file is committed to the repo and updated periodically. Staff should never print it -- they should always access the live version through the app so they're reading the latest copy.

## Requirements

### 1. Add a "Staff Manual" link in the admin navigation

Add a link to the staff manual in the admin shell's navigation or user menu dropdown (top-right where the email/role and sign-out link are). The link should:

- Open `/docs/staff-manual.pdf` in a new browser tab (`target="_blank"`)
- Use a book or document icon (from whatever icon library is already in use -- likely Ant Design icons)
- Be visible to both **admin** and **operator** roles
- Label it "Staff Manual"
- Be unobtrusive -- it's a utility link, not a primary nav item. The user menu dropdown or a help/resources section is the right place.

### 2. Do NOT build a PDF viewer

Do not embed the PDF in an iframe or build a viewer component. Just open the raw PDF in a new tab. Every browser has a built-in PDF viewer. Keep it simple.

### 3. File location

The PDF is already committed at:
```
frontend/public/docs/staff-manual.pdf
```

The link href should be `/docs/staff-manual.pdf`. Do not use an absolute URL -- the relative path works in all environments (local dev, staging, production).

## Implementation notes

- Look at the existing user menu dropdown in the admin shell (likely in `App.tsx` or a layout/shell component) for where sign-out, "My Permit", and impersonation links live. The staff manual link goes in that same menu.
- This is a static file link, not a route. Do not add a React Router route for it.
- No backend changes needed.
