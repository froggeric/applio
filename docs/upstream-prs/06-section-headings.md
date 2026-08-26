# PR 6 — branch `upstream-pr/section-headings` (commit 57450f30) — DRAFT, NOT SUBMITTED

## Title

Add section headings so screen readers can navigate the tabs

## Body

VoiceOver and NVDA let you jump between the sections of a page with a headings rotor, but that only works if the page has headings. Applio's inference, TTS and real-time tabs had none: each is a long run of controls with no way to skip from "pick a model" to "run the job" without tabbing through everything in between.

The download tab already marks its sections with `gr.Markdown("## ...")`, so this follows the same pattern where it is missing:

- inference: "Model Selection" at the top, "Conversion" above the run controls, in both the single and the batch tab
- TTS: "Model Selection", "TTS Settings", "Conversion"
- real-time: "Model Selection" and "Advanced Settings" inside the model settings tab

The other tabs were left alone on purpose. Training is five top-level accordions that already carry their own titles, and the settings and extras tabs are small, labeled clusters; a heading right above a titled accordion or a named group would just say the same thing twice.

The new strings are in en_US.json as well, following the note on #1277.

Verified with VoiceOver: the rotor lists the sections and jumping works.
