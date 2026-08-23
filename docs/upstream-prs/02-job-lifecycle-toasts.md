# PR 2 — branch `upstream-pr/job-lifecycle-toasts` (commit 89b504e7)

## Title

Announce job start and completion with toasts for screen reader users

## Body

A blind user running Applio gets no signal when a job starts or finishes. Conversions, TTS, preprocessing, extraction and model link downloads all end in silence, and the result textboxes are not read aloud, so the only way to tell a job is done is to keep checking by hand.

Gradio toasts are announced by screen readers (they render with role=status and aria-live). Applio already uses them for the pretrained model download and the prerequisites check. This change extends that to the other long-running jobs:

- single conversion and TTS: toast on start, toast with the result message on completion, warning toast on error
- preprocessing, feature extraction and model link downloads: wrapped so they announce start, the returned result, and errors (a returned message mentioning "error" or "failed" is shown as a warning)
- training: announces its start. A run can last hours, so completion feedback needs its own approach and is left out here

Start messages are translated like the rest of the UI. Error toasts reuse the exact strings these functions already return, so there are only eight new translation strings.

Batch conversion and the real-time engine are left out for now; they need progress reporting rather than single toasts.

Tested on macOS with VoiceOver: start and completion of a conversion, a TTS run, preprocessing, extraction and a model download are all spoken. The calls are plain gradio toasts and behave the same on every platform. This came out of an accessibility pass on the macOS port. The same class of problem has come up in gradio itself (gradio-app/gradio#12855, fixed in #13542), reported by a blind screen-reader user; Applio came up in that thread as another app built on it.
