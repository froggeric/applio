# PR 7 — branch `upstream-pr/tuple-choices` (commit 6d4b1f75) — DRAFT, NOT SUBMITTED

## Title

Show friendly names in the file dropdowns (screen reader accessibility)

## Body

The model, index and audio dropdowns list raw relative paths, so picking a model with a screen reader means listening to "logs/AttentiveWindow/crepe_han_window_Titan48k/crepe_han_window_Titan48k.pth" — the part that identifies the model is the tail, and everything before it is the same for every entry on the list.

Gradio dropdowns accept (label, value) pairs, where the label is what the user sees and hears, and the value is what reaches the handler. This converts the file dropdowns in the inference, TTS, real-time and training tabs to use them: the label is the file name without extension ("crepe_han_window_Titan48k"), and when two files share a name the parent folder is appended to tell them apart. The value stays the exact path, so every handler and downstream function receives what it receives today; sorting is unchanged.

One small fix fell out of this: the "Refresh embedders" button on the training tab returned a bare list that set the dropdown's value but never refreshed its choices, so newly added embedders didn't appear until reload. It now returns a proper update, matching what the same button does on the other tabs.

The SID, voice and device lists already read concisely and are untouched.

Verified on macOS with VoiceOver: model and index lists read as names, and a picked model converts as before.
