# PR 8 — branch `upstream-pr/i18n-strings` (commit 2aadfbe5) — DRAFT, NOT SUBMITTED

## Title

Translate the remaining user-facing strings and show real language names in the picker

## Body

A pass over the app found about forty strings the user sees but the translation system never touches: the prerequisites check messages on the training tab, model path errors, several info and warning toasts, the plugin install messages, and a number of smaller ones. All of them are now wrapped in i18n() like the rest of the UI, and the English keys are in en_US.json so the other locales pick them up through the usual flow.

The language picker used to show raw codes like "fr_FR" and "pt_BR". It now shows each language in its own spelling — "Français (fr_FR)", "日本語 (ja_JP)" — built at runtime from the files that are actually installed, so it stays correct when locales are added (a locale without a name entry simply shows its code). The stored setting is still the raw code; nothing about how the choice is saved changes.

One detection detail: the real-time failure toasts added in #1276 spotted failures by looking for English words in the status text. With those strings now translatable that scan would silently stop working in other languages, so it now recognizes failures structurally — a status update is a failure when it re-enables the start button — which works the same in every language. Tested against the translated yield shapes.

Two things were deliberately left alone. The return strings of the run_* functions in core.py feed the failure toasts from #1271, which match on English words; translating those would make failure reporting depend on the UI language, so they stay until there is a proper status contract to key on. And the record start/stop button has a pre-existing state-machine quirk with translated labels that this PR does not attempt to fix.

Verified on macOS with VoiceOver in English and Spanish.
