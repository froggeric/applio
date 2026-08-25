# PR 4 — branch `upstream-pr/extra-job-toasts` (commit f12afdac) — DRAFT, NOT SUBMITTED

## Title

Accessibility improvements: add toasts to the remaining long-running jobs

## Body

PR #1271 and #1275 cover conversions, TTS, training, preprocessing, extraction and downloads. Five remaining tasks give little or no spoken feedback: blending two models, installing a plugin, the real-time engine, loading model information and launching tensorboard.

This PR adds toasts to all five of them:

- voice blender: announces the mix start, the result and errors, and confirms when a dropped model lands in a slot (a drop is easy to miss when you can't see the field fill in)
- plugin install: start and errors (success toast already exists)
- real time engine: start and failures, including validation messages like "Please select valid input/output devices!", which previously appeared only in the status label
- model information and tensorboard: toast when the info is loaded and when the board is ready

The new messages flow through the existing translation setup. The real time wrapper also warns on the engine's own stop messages ("...Stopping.", "Aborting conversion."), which means the user also gets a spoken alert when a run fails.

Tested successfully on macos with voiceover.