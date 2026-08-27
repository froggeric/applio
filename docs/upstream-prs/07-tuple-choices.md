# PR 7 — branch `upstream-pr/tuple-choices` (commit 6d4b1f75) — DRAFT, NOT SUBMITTED

## Title

Accessibility improvements: show friendly names in the file dropdowns

## Body

The model, index and audio dropdowns show raw relative paths. Picking a model with a screen reader is tedious and easily prone to error. For example, when listing a model named "crepe_han_window_Titan48k", the user could first have to listening to a long string such as "logs/AttentiveWindow/crepe_han_window_Titan48k/crepe_han_window_Titan48k.pth". Imagine having to go through a list of a few of those...

Gradio dropdowns accept (label, value) pairs. The label is what the user sees and hears. The value is what the handler uses. This PR modifies the file dropdowns in the inference, TTS, real-time and training tabs to use the labels (file name without extension, such as "crepe_han_window_Titan48k"). When two files have the same name, the parent folder is appended to tell them apart. The value remain unchanged, exact path, ensuring every handler and downstream function receives exactly the same data as before this PR. Sorting is unchanged.

One small existing bug was found and fixed while making this change: the "Refresh embedders" button on the training tab returned a list that set the dropdown's value, but it never refreshed. Newly added embedders didn't appear until reload. It now returns a proper update, matching what the same button does on the other tabs.

The SID, voice and device lists already read concisely and are untouched.

Verified successfully on macos with voiceover.