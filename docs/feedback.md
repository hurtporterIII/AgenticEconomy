# Feedback

## What Worked

- Layered build process (structure -> skeleton -> economy -> services -> proof) made integration stable.
- Shared `state` model kept agent behavior and proof logging simple.
- Pricing every action with `tx_hash` made demo verification straightforward.
- Minimal API endpoints were enough to show live state, events, and transaction volume.

## What Did Not Work Well

- Placeholder tx rail still needs real Circle/Arc settlement for production proof.
- AI provider integration quality depends on key setup and provider response format.
- Without a small deterministic scenario seed, some demo runs can vary in event mix.

## Friction Points

- Tooling friction around environment secrets and endpoint configuration slowed integration.
- Event verbosity grows quickly; hard to read without timeline filtering in UI.
- Import path consistency (`backend.*` vs local package imports) can cause confusion.

## What Should Be Improved By Platform Providers

- Provide a sanctioned, minimal Arc test harness with canned wallets and explorer links.
- Provide one-click Gemini/Featherless starter templates with consistent response schemas.
- Add official guidance for micro-transaction economics benchmarks (cost per action tiers).
- Improve hackathon submission templates for proof artifacts (tx sample, count screenshot, API trace).

---

## Circle / Arc (hackathon feedback template — fill before submit)

**What worked well**

- (Example: developer-controlled wallet client initialization, testnet faucet behavior, error messages when rate-limited.)

**What was confusing or costly in time**

- (Example: which env vars are mandatory vs optional for a minimal Arc USDC transfer proof.)

**One concrete improvement**

- (Example: a single “happy path” curl sequence in official docs that returns `tx_hash` on Arc testnet within one page.)
