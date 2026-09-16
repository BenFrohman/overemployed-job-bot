## Summary

<!-- What changed and why. -->

## Security checklist

- [ ] No secrets, `.env` files, private keys, customer data, or resumes are included
- [ ] Tenant isolation and auth behavior are unchanged or intentionally updated
- [ ] Stripe / webhook handling remains signature-verified if billing code changed
- [ ] `.gitignore` still excludes local data and credentials

## Test plan

<!-- How this was verified. -->
