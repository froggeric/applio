# PR 6 — branch `upstream-pr/section-headings` (commit 57450f30) — DRAFT, NOT SUBMITTED

## Title

Accessibility improvements: add section headings, for screen readers to be able to navigate tabs more easily

## Body

Accessibility tools let you jump between sections of a page by iterating through the list of headings. But that only works if the page contains headings, which were missing from some tabs.

The download tab already used `gr.Markdown("## ...")` to mark its sections. This follows the same pattern.

- inference: "Model Selection" at the top, "Conversion" above the run controls, in both the single and the batch tab
- TTS: "Model Selection", "TTS Settings", "Conversion"
- real-time: "Model Selection" and "Advanced Settings" inside the model settings tab

The other tabs were left alone on purpose. Training is five top-level accordions that already have their own titles. The Settings and Extras tabs are small, labeled clusters with named groups.

I have added the new strings in en_US.json as well.

Verified on macos with voiceover.