# PR 5 — branch `upstream-pr/label-clarity` (commit 9397a663) — DRAFT, NOT SUBMITTED

## Title

Label controls so screen readers can tell them apart

## Body

Thirteen text boxes across the app are all labelled "Output Information", and seven buttons are just "Refresh". The training page alone shows three of those boxes and two of those buttons at once, so listing a page's controls with a screen reader gives you no way to tell which job an output belongs to, or what a button reloads, without finding it visually first.

Every one of those now says what it is: "Preprocess output", "Feature extraction output", "Training output", "Conversion output" versus "Batch conversion output", and so on. The Refresh buttons get the same treatment as the specific ones Applio already has ("Refresh Presets", "Refresh Audio Devices", "Refresh embedders"), each naming what it actually reloads: "Refresh formant presets", "Refresh models and indexes", "Refresh models and datasets".

The voice blender had two drop zones and two path fields with identical names; they are now first/second. The drop zone labels only mentioned dragging, but each one is also a keyboard-operable browse button, so the new wording mentions both ("Drop a plugin.zip here or use the browse button to install it"). The TensorBoard iframe gets a title so it is announced as something other than an empty frame.

The new labels go through the translation setup like the rest of the UI; until a locale catches up it shows the English text, which is how new strings always behave in Applio. Two small notes: one of the thirteen renamed text boxes lives in a file that isn't mounted anywhere (renamed anyway so a search finds no strays), and the realtime Refresh button also reloads audio devices in full mode, but the label says "Refresh models and indexes" because that is what it does in client mode and a dedicated device button already exists.

Checked with VoiceOver: you can tell every control apart.
