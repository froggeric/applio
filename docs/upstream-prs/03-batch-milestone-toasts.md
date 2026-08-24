# PR 3 — branch `upstream-pr/batch-milestone-toasts` (commit cd16c5ce) — DRAFT, NOT SUBMITTED

## Title

Announce batch conversion progress with toasts

## Body

#1271 covered single conversions and the training stages. Batch conversion was initially left out. It is the longest  silent gap of all: a large folder can run for a long time with no feedback a screen reader can hear.

The tab layer only sees the start and end of the call, so the announcements come from inside the conversion loop:

- a toast when the batch starts, with the file count
- at 25, 50 and 75 percent, a toast like "12/48 files converted (25%)"
- on completion, a toast with the converted and skipped counts and the elapsed time
- on failure, a warning toast with the error before it re-raises

Batches under eight files skip the milestone toasts and only get start and completion, so quick jobs don't chatter. Skipped files count toward the progress, so the percentages track how far through the folder the run is. The helper imports gradio lazily and falls back to a plain print when no interface is running, so the module still works headless. Messages are short and mostly numbers; they stay in English because the conversion engine doesn't use the translation setup, and I'd rather not couple it to the UI's locale files for the sake of four words.

Tested on macOS with VoiceOver across batches of different sizes: the milestones land on the right files and completion is spoken.
