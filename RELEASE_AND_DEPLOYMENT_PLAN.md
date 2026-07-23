# Release and private Cloudflare beta plan

## Complete in v0.0.6

- Windows Credential Manager holds the local Worker session token.
- online_sync.json contains no session token.
- Git ignores local state, secrets, dependencies and generated releases.
- Python and Worker tests run from one verification script.

## Required before remote deployment

1. Run the Windows Credential Manager migration test on the target laptop.
2. Create a private Git repository and push the tested source.
3. Create a separate remote D1 database. Do not reuse or expose the local
   development database.
4. Configure production Worker secrets through Wrangler; never place them in
   source files or Git.
5. Deploy a private Worker URL first and create a new remote test account.
6. Keep registration invite-only until two-device sync, logout, expiry and
   recovery tests pass.

## Website scope after the private beta

The local Python dashboard remains the tracker control UI. A public website can
later provide account profiles and leaderboard viewing through a separate
Cloudflare Pages frontend talking to the Worker API. It must not receive a
local tracker session token or raw input data.
