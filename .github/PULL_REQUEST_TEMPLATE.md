## Summary

Briefly describe what changed and why.

## Verification Checklist

- [ ] `npm run verify:integrity` passes (`translator.py` MD5 untouched, `32/32` selftests OK)
- [ ] `npm run test:backend` passes (`pytest functions/tests -v`)
- [ ] `npm run build:web` passes (`tsc -b && vite build`)
- [ ] `npm run test:e2e` passes (desktop, tablet, mobile, WCAG 2.2 AA, and PWA checks)
- [ ] No secrets, `.env.production`, or local filesystem paths are committed
