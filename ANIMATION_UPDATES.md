# LANDED animation updates

Updated the frontend so animations reliably load:

- Removed the aggressive global reduced-motion CSS override that collapsed transitions to 0.01ms.
- Added page entrance animations for hero, stats, browse and resume sections.
- Added floating hero job-card motion and assistant FAB pulse.
- Added animated job-card reveal when search results render.
- Kept counter animation via requestAnimationFrame.
- Added CSS/JS cache-busting query parameters (`v=20260822`) so browsers don't keep old static assets.
- Added a small note under "jobs added today".
- Updated browser title and brand text to LANDED.
