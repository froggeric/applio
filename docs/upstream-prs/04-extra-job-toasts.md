# PR 4 — branch `upstream-pr/extra-job-toasts` (commit f12afdac) — DRAFT, NOT SUBMITTED

## Title

Add toasts to the remaining long-running jobs

## Body

#1271 and #1275 cover conversions, TTS, training, preprocessing, extraction and downloads. Five other corners of the app give little or no spoken feedback: blending two models, installing a plugin, the real-time engine, loading model information and launching TensorBoard.

This adds toasts to those five:

- voice blender: announces the mix start, the result and errors, and confirms when a dropped model lands in a slot (a drop is easy to miss when you can't see the field fill in)
- plugin install: start and errors; the successful install already toasts on its own
- real-time engine: start and failures, including the validation messages like "Please select valid input/output devices!", which previously appeared only in the status label
- model information and TensorBoard: a toast when the info is loaded and when the board is ready

The new messages go through the existing translation setup. The real-time wrapper also warns on the engine's own stop messages ("...Stopping.", "Aborting conversion."), so a run that dies mid-way says why instead of going quiet.

Same testing setup as the earlier PRs: macOS with VoiceOver, each new toast heard as described.
