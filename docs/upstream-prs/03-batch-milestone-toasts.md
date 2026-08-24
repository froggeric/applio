# PR 3 — branch `upstream-pr/batch-milestone-toasts` (commit cd16c5ce) — DRAFT, NOT SUBMITTED

## Title

Accessibility improvement: announce batch conversion progress with toasts

## Body

PR #1271 covered single conversions and the training stages. Batch conversion was initially left out. However, a large folder can run for a long time with no feedback for blind or disabled users.

The tab layer only sees the start and end of the call. The new announcements come from inside the conversion loop. Here are the toasts we now show with this PR:

- a toast when the batch starts, with the file count
- at 25%, 50% and 75%, a progress toast; example: "12/48 files converted (25%)"
- on completion, a toast with the converted and skipped counts and the elapsed time
- on failure, a warning toast with the error

Batches under 8 files skip the milestone toasts and only get start and completion. The new progress toasts are only needed on long jobs. Skipped files count toward the progress; the percentages track how far through the folder the run is. The helper imports gradio lazily and falls back to a plain print when no interface is running, meaning the module still works headless. Messages are short, and include useful numbers; they stay in english because the conversion engine doesn't use the translation setup, and I'd rather not couple it to the UI's locale files for the sake of four words.

Tested successfully on macOS with Voiceover across batches of different sizes.