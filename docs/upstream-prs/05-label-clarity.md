# PR 5 — branch `upstream-pr/label-clarity` (commit 9397a663) — DRAFT, NOT SUBMITTED

## Title

Accessibility improvements: differentiate controls through unique labels, for screen readers

## Body

There are 13 text boxes across the app, with the same label, "Output Information"; and 7 buttons all titled "Refresh". This makes it impossible for a screen reader to differentiate them. For example, the training page shows three "Output information" boxes and 2 "Refresh" buttons at once, making it impossible for a user requiring accessibility to know which one to use or view.

After this PR, each of those text boxes will clearly state what it is: "Preprocess output", "Feature extraction output", "Training output", "Conversion output", "Batch conversion output", etc. Same for the refresh buttons: "Refresh formant presets", "Refresh models and indexes", "Refresh models and datasets" (applio already has "Refresh Presets", "Refresh Audio Devices", "Refresh embedders").

As for the voice blender, it has 2 drop zones and 2 path fields with identical names; they are now first and second. The drop zone labels only mentioned dragging, but since they also a keyboard operable browse button, the new wording is updated to mention both methods ("Drop a plugin.zip here or use the browse button to install it"). The tensorboard iframe was missing a title; adding it so that it gets a announced properly by a screen reader instead an empty frame.

All the new labels use the same translation as the rest of the UI.

Verified with voiceover on macos.