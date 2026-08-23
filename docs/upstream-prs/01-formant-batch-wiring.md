# PR 1 — branch `upstream-pr/formant-batch-wiring` (commit 54c92069)

## Title

Wire the batch formant toggle to its own checkbox

## Body

The batch formant options don't follow their own checkbox. Their visibility is driven by the single tab's checkbox instead, so checking the batch toggle does nothing unless the single tab's checkbox is also checked.

The handler registration passes `formant_shifting` where it should pass `formant_shifting_batch`:

```diff
 formant_shifting_batch.change(
     fn=toggle_visible_formant_shifting,
-    inputs=[formant_shifting],
+    inputs=[formant_shifting_batch],
```

Found while making the inference tabs usable with VoiceOver. The two tabs look identical, so this is easy to miss visually. With a screen reader it stands out immediately, because the toggle you just changed does nothing to the page you are on.
